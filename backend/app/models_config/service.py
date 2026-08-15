"""ModelConfigService — 模型配置编排。

职责：
- Provider CRUD（含 api_key 掩码回写保护、目录导入预填模型）
- 模型管理（增删、/models 端点同步、元数据合并）
- models.dev 目录同步与查询
- 全局当前模型（可空可删）
- 测试连接（发最小请求验证）
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from litellm import acompletion

from app.config.service import ConfigService
from app.models_config.litellm_mapping import (
    build_litellm_name,
    default_base_url,
    validate_kind,
)
from app.net.proxy import (
    build_proxy_client,
    close_proxy_client,
    fallback_direct_enabled,
    get_proxy_url,
    is_conn_error,
)
from app.models_config.schema import (
    CatalogMeta,
    CurrentModel,
    ModelEntry,
    ModelProvider,
)
from app.models_config.store import SETTING_CURRENT_MODEL, ModelConfigStore
from app.models_config.sync_models_dev import (
    get_catalog_provider,
    get_catalog_provider_models,
    list_catalog_providers,
    load_catalog_file,
    save_catalog_file,
    fetch_catalog,
    count_models,
)
from app.models_config.sync_provider import (
    ProviderSyncError,
    fetch_provider_models,
)

log = logging.getLogger(__name__)

# api_key 掩码
MASK = "***"


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


class ModelConfigService:
    """模型配置服务，模块唯一对外入口。"""

    def __init__(
        self,
        store: ModelConfigStore,
        data_dir: Path,
        config_service: ConfigService | None = None,
    ) -> None:
        self._store = store
        self._data_dir = data_dir
        self._config = config_service or ConfigService.get_instance()

    # ─── Provider CRUD ────────────────────────────────────

    async def list_providers(self) -> list[dict[str, Any]]:
        providers = await self._store.list_providers()
        return [self._mask_provider(p) for p in providers]

    async def create_provider(self, data: dict[str, Any]) -> ModelProvider:
        kind = data.get("kind") or ""
        validate_kind(kind)

        provider_id = (data.get("provider_id") or "").strip()
        if not provider_id:
            raise ValueError("provider_id 不能为空")
        if await self._store.get_provider(provider_id):
            raise ValueError(f"provider 已存在: {provider_id}")

        base_url = (data.get("base_url") or "").strip()
        # 目录导入：base_url 为空时从目录 api 字段预填
        if not base_url and data.get("source") == "catalog":
            catalog = load_catalog_file(self._data_dir)
            if catalog:
                info = get_catalog_provider(catalog, provider_id)
                if info and info.get("api"):
                    base_url = info["api"]
        if kind == "openai_like" and not base_url:
            raise ValueError("openai_like 类型必须填写 base_url")

        now = _now_iso()
        provider = ModelProvider(
            provider_id=provider_id,
            name=(data.get("name") or provider_id).strip(),
            kind=kind,
            base_url=base_url or default_base_url(kind),
            models_url=(data.get("models_url") or "").strip(),
            api_key=(data.get("api_key") or "").strip(),
            enabled=bool(data.get("enabled", True)),
            use_proxy=bool(data.get("use_proxy", False)),
            source=data.get("source", "custom"),
            created_at=now,
            updated_at=now,
        )
        await self._store.create_provider(provider)

        # 按 model_ids 导入指定模型（含 models.dev 元数据回填，enabled=true）
        model_ids = data.get("model_ids")
        if isinstance(model_ids, list) and model_ids:
            await self._import_model_ids(provider, model_ids)

        log.info("创建 provider: %s (%s)", provider_id, kind)
        return provider

    async def update_provider(
        self, provider_id: str, data: dict[str, Any]
    ) -> ModelProvider:
        existing = await self._store.get_provider(provider_id)
        if existing is None:
            raise KeyError(f"provider 不存在: {provider_id}")

        kind = data.get("kind") or existing.kind
        validate_kind(kind)

        base_url = data.get("base_url", existing.base_url) or ""
        if kind == "openai_like" and not base_url:
            raise ValueError("openai_like 类型必须填写 base_url")

        api_key = data.get("api_key", existing.api_key)
        # 掩码回写保护：前端回传 "***" 时保留原值
        if api_key == MASK:
            api_key = existing.api_key

        updated = existing.model_copy(
            update={
                "name": (data.get("name") or existing.name).strip(),
                "kind": kind,
                "base_url": base_url,
                "models_url": (data.get("models_url") or "").strip()
                if "models_url" in data
                else existing.models_url,
                "api_key": api_key,
                "enabled": bool(data.get("enabled", existing.enabled)),
                "use_proxy": bool(data.get("use_proxy", existing.use_proxy)),
                "source": data.get("source", existing.source),
                "updated_at": _now_iso(),
            }
        )
        await self._store.update_provider(updated)

        # 禁用 provider → 若当前模型在此 provider 则清空 current
        if existing.enabled and not updated.enabled:
            await self._clear_current_if_matches(provider_id, None)

        # model_ids 非 null → 同步启用集合（未列出的现有模型置隐藏，不删除；新 id 插入）
        model_ids = data.get("model_ids")
        if model_ids is not None:
            await self._apply_enabled_set(updated, model_ids)

        return updated

    async def delete_provider(self, provider_id: str) -> None:
        existing = await self._store.get_provider(provider_id)
        if existing is None:
            raise KeyError(f"provider 不存在: {provider_id}")
        await self._store.delete_provider(provider_id)
        # 若删除的是当前模型所在 provider → 清空当前模型
        await self._clear_current_if_matches(provider_id, None)
        log.info("删除 provider: %s", provider_id)

    # ─── 模型管理 ─────────────────────────────────────────

    async def list_models(self, provider_id: str) -> list[ModelEntry]:
        provider = await self._store.get_provider(provider_id)
        if provider is None:
            raise KeyError(f"provider 不存在: {provider_id}")
        return await self._store.list_entries(provider_id)

    async def add_model(self, provider_id: str, model_id: str) -> ModelEntry:
        """手动添加模型；优先从目录缓存回填元数据。"""
        provider = await self._store.get_provider(provider_id)
        if provider is None:
            raise KeyError(f"provider 不存在: {provider_id}")
        model_id = model_id.strip()
        if not model_id:
            raise ValueError("model_id 不能为空")
        if await self._store.get_entry(provider_id, model_id):
            raise ValueError(f"模型已存在: {model_id}")

        meta, meta_source = await self._lookup_metadata(provider, model_id)
        entry = ModelEntry(
            provider_id=provider_id,
            model_id=model_id,
            display_name=meta.get("name") or model_id,
            litellm_name=build_litellm_name(provider.kind, model_id),
            meta_source=meta_source,
            metadata=meta,
        )
        await self._store.upsert_entry(entry)
        return entry

    async def remove_model(self, provider_id: str, model_id: str) -> None:
        entry = await self._store.get_entry(provider_id, model_id)
        if entry is None:
            raise KeyError(f"模型不存在: {provider_id}/{model_id}")
        await self._store.delete_entry(provider_id, model_id)
        await self._clear_current_if_matches(provider_id, model_id)

    async def set_model_enabled(
        self, provider_id: str, model_id: str, enabled: bool
    ) -> ModelEntry:
        """启用/隐藏模型；隐藏当前模型时自动清空 current。"""
        entry = await self._store.get_entry(provider_id, model_id)
        if entry is None:
            raise KeyError(f"模型不存在: {provider_id}/{model_id}")
        if entry.enabled == enabled:
            return entry
        updated = entry.model_copy(update={"enabled": enabled})
        await self._store.upsert_entry(updated)
        if not enabled:
            await self._clear_current_if_matches(provider_id, model_id)
        return updated

    async def sync_provider_models(self, provider_id: str) -> dict[str, Any]:
        """调 /models 端点同步，覆盖合并模型列表。"""
        provider = await self._store.get_provider(provider_id)
        if provider is None:
            raise KeyError(f"provider 不存在: {provider_id}")

        try:
            proxy_url = get_proxy_url(self._config) if provider.use_proxy else None
            fetched = await fetch_provider_models(
                provider,
                models_url=provider.models_url or None,
                proxy_url=proxy_url,
                fallback_direct=fallback_direct_enabled(self._config),
            )
        except ProviderSyncError as e:
            raise ValueError(str(e)) from e

        # 保留既有启用/隐藏状态（隐藏 ≠ 删除，同步不重置用户选择）
        old_enabled = {
            e.model_id: e.enabled
            for e in await self._store.list_entries(provider_id)
        }

        # 回填 models.dev 元数据（/models 只有 id，详细能力以目录为准）
        entries: list[ModelEntry] = []
        for item in fetched:
            mid = item["id"]
            meta, meta_source = await self._lookup_metadata(provider, mid)
            entries.append(
                ModelEntry(
                    provider_id=provider_id,
                    model_id=mid,
                    display_name=item.get("display_name") or meta.get("name") or mid,
                    litellm_name=build_litellm_name(provider.kind, mid),
                    enabled=old_enabled.get(mid, True),
                    meta_source=meta_source,
                    metadata=meta,
                )
            )

        await self._store.replace_entries(provider_id, entries)
        log.info("provider %s 模型同步完成: %d 个", provider_id, len(entries))
        return {"provider_id": provider_id, "count": len(entries)}

    async def preview_provider_models(
        self, data: dict[str, Any]
    ) -> list[dict[str, str]]:
        """预览：按给定参数调 /models 端点拉取模型列表（不落库），供添加向导使用。"""
        kind = data.get("kind") or ""
        validate_kind(kind)
        provider = ModelProvider(
            provider_id="__preview__",
            name="preview",
            kind=kind,
            base_url=(data.get("base_url") or "").strip(),
            models_url=(data.get("models_url") or "").strip(),
            api_key=(data.get("api_key") or "").strip(),
            use_proxy=bool(data.get("use_proxy", False)),
            source="custom",
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        try:
            proxy_url = get_proxy_url(self._config) if provider.use_proxy else None
            return await fetch_provider_models(
                provider,
                models_url=provider.models_url or None,
                proxy_url=proxy_url,
                fallback_direct=fallback_direct_enabled(self._config),
            )
        except ProviderSyncError as e:
            raise ValueError(str(e)) from e

    async def _lookup_metadata(
        self, provider: ModelProvider, model_id: str
    ) -> tuple[dict[str, Any], str]:
        """从目录缓存查找模型元数据；未命中返回空 custom。"""
        catalog = load_catalog_file(self._data_dir)
        if catalog:
            models = get_catalog_provider_models(catalog, provider.provider_id)
            if models and model_id in models:
                return models[model_id], "models_dev"
            # 目录 provider id 与自定义 id 不同时，按全局模型名搜索
            for pid, p in catalog.items():
                m = (p.get("models") or {}).get(model_id)
                if m:
                    return m, "models_dev"
        return {}, "custom"

    # ─── models.dev 目录 ──────────────────────────────────

    async def catalog_status(self) -> dict[str, Any]:
        meta = await self._store.get_catalog_meta()
        has_cache = (self._data_dir / "models_dev_catalog.json").exists()
        return {
            "synced_at": meta.synced_at,
            "data_date": meta.data_date,
            "etag": meta.etag,
            "provider_count": meta.provider_count,
            "model_count": meta.model_count,
            "has_cache": has_cache,
        }

    async def sync_catalog(self) -> dict[str, Any]:
        """同步 models.dev 目录（ETag 增量）。"""
        meta = await self._store.get_catalog_meta()
        data, new_etag, data_date, changed = await fetch_catalog(
            meta.etag,
            proxy_url=get_proxy_url(self._config),
            fallback_direct=fallback_direct_enabled(self._config),
        )

        if not changed:
            return {"status": "unchanged", "data_date": meta.data_date}

        save_catalog_file(self._data_dir, data)
        new_meta = CatalogMeta(
            etag=new_etag,
            data_date=data_date or meta.data_date,
            synced_at=_now_iso(),
            provider_count=len(data),
            model_count=count_models(data),
        )
        await self._store.save_catalog_meta(new_meta)
        log.info(
            "models.dev 目录同步完成: %d providers, %d models",
            new_meta.provider_count,
            new_meta.model_count,
        )
        return {
            "status": "updated",
            "data_date": new_meta.data_date,
            "provider_count": new_meta.provider_count,
            "model_count": new_meta.model_count,
        }

    def catalog_providers(self, search: str = "") -> list[dict[str, Any]]:
        catalog = load_catalog_file(self._data_dir)
        if not catalog:
            return []
        return list_catalog_providers(catalog, search)

    def catalog_provider_models(self, provider_id: str) -> dict[str, Any] | None:
        catalog = load_catalog_file(self._data_dir)
        if not catalog:
            return None
        return get_catalog_provider_models(catalog, provider_id)

    async def _import_model_ids(
        self, provider: ModelProvider, model_ids: list[str]
    ) -> int:
        """按 id 列表导入模型（含 models.dev 元数据回填，enabled=true）。"""
        entries: list[ModelEntry] = []
        for mid in model_ids:
            mid = mid.strip()
            if not mid:
                continue
            meta, meta_source = await self._lookup_metadata(provider, mid)
            entries.append(
                ModelEntry(
                    provider_id=provider.provider_id,
                    model_id=mid,
                    display_name=meta.get("name") or mid,
                    litellm_name=build_litellm_name(provider.kind, mid),
                    meta_source=meta_source,
                    metadata=meta,
                )
            )
        if entries:
            await self._store.replace_entries(provider.provider_id, entries)
        return len(entries)

    async def _apply_enabled_set(
        self, provider: ModelProvider, model_ids: list[str]
    ) -> None:
        """把 provider 的模型启用状态同步为给定集合（隐藏=保留不删除）。

        - 现有条目：在集合内 → 启用；不在 → 隐藏（enabled=false）
        - 集合内新 id：插入并启用
        - 当前模型被置隐藏 → 清空 current
        """
        target = {mid.strip() for mid in model_ids if mid.strip()}
        existing = await self._store.list_entries(provider.provider_id)
        for entry in existing:
            should_enable = entry.model_id in target
            if entry.enabled != should_enable:
                await self._store.upsert_entry(
                    entry.model_copy(update={"enabled": should_enable})
                )
        existing_ids = {e.model_id for e in existing}
        for mid in target - existing_ids:
            meta, meta_source = await self._lookup_metadata(provider, mid)
            await self._store.upsert_entry(
                ModelEntry(
                    provider_id=provider.provider_id,
                    model_id=mid,
                    display_name=meta.get("name") or mid,
                    litellm_name=build_litellm_name(provider.kind, mid),
                    meta_source=meta_source,
                    metadata=meta,
                )
            )
        # 当前模型被置隐藏 → 清空
        current = await self.get_current()
        if (
            current
            and current.provider_id == provider.provider_id
            and current.model_id not in target
        ):
            await self.clear_current()
            log.info(
                "当前模型已清空（被隐藏）: %s/%s",
                provider.provider_id,
                current.model_id,
            )

    # ─── 全局当前模型 ─────────────────────────────────────

    async def get_current(self) -> CurrentModel | None:
        raw = await self._store.get_setting(SETTING_CURRENT_MODEL)
        if not raw:
            return None
        provider_id = raw.get("provider_id")
        model_id = raw.get("model_id")
        entry = await self._store.get_entry(provider_id or "", model_id or "")
        if entry is None or not entry.enabled:
            return None
        provider = await self._store.get_provider(provider_id or "")
        if provider is None or not provider.enabled:
            return None
        return CurrentModel(
            provider_id=provider_id,
            model_id=model_id,
            litellm_name=entry.litellm_name,
            display_name=entry.display_name,
        )

    async def set_current(self, provider_id: str, model_id: str) -> CurrentModel:
        entry = await self._store.get_entry(provider_id, model_id)
        if entry is None:
            raise KeyError(f"模型不存在: {provider_id}/{model_id}")
        if not entry.enabled:
            raise ValueError(f"模型已禁用: {model_id}")
        provider = await self._store.get_provider(provider_id)
        if provider is None or not provider.enabled:
            raise ValueError("provider 不存在或已禁用")
        await self._store.set_setting(
            SETTING_CURRENT_MODEL,
            {"provider_id": provider_id, "model_id": model_id},
        )
        return CurrentModel(
            provider_id=provider_id,
            model_id=model_id,
            litellm_name=entry.litellm_name,
            display_name=entry.display_name,
        )

    async def clear_current(self) -> None:
        await self._store.delete_setting(SETTING_CURRENT_MODEL)

    async def _clear_current_if_matches(
        self, provider_id: str, model_id: str | None
    ) -> None:
        """删除 provider/模型后，若命中当前模型则清空。"""
        current = await self.get_current()
        if current is None:
            return
        if current.provider_id == provider_id and (
            model_id is None or current.model_id == model_id
        ):
            await self.clear_current()
            log.info("当前模型已清空（被删除）: %s/%s", provider_id, model_id)

    # ─── 测试连接 ─────────────────────────────────────────

    async def resolve_model(
        self, provider_id: str, model_id: str
    ) -> dict[str, Any]:
        """解析模型为 litellm 调用参数（供 chat 运行时使用）。

        Returns:
            {"litellm_name": str, "llm_extra": dict, "provider_id": str, "model_id": str}
        """
        entry = await self._store.get_entry(provider_id, model_id)
        if entry is None:
            raise KeyError(f"模型不存在: {provider_id}/{model_id}")
        if not entry.enabled:
            raise ValueError(f"模型已禁用: {model_id}")
        provider = await self._store.get_provider(provider_id)
        if provider is None or not provider.enabled:
            raise ValueError("provider 不存在或已禁用")
        llm_extra: dict[str, Any] = {}
        if provider.api_key:
            llm_extra["api_key"] = provider.api_key
        if provider.base_url:
            llm_extra["base_url"] = provider.base_url
        # LLM 请求是否走代理（透传给 native_litellm_client）
        llm_extra["use_proxy"] = provider.use_proxy
        return {
            "litellm_name": entry.litellm_name,
            "llm_extra": llm_extra,
            "provider_id": provider_id,
            "model_id": model_id,
        }

    async def test_connection(
        self, provider_id: str, model_id: str
    ) -> dict[str, Any]:
        """向模型发最小请求验证连通性。"""
        provider = await self._store.get_provider(provider_id)
        if provider is None:
            raise KeyError(f"provider 不存在: {provider_id}")
        if not provider.api_key:
            raise ValueError("provider 未配置 api_key")

        model = build_litellm_name(provider.kind, model_id)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        if provider.api_key:
            kwargs["api_key"] = provider.api_key
        if provider.base_url:
            kwargs["api_base"] = provider.base_url

        # 代理：provider.use_proxy 开启且全局代理可用时走代理，连接失败回退直连
        proxy_client: AsyncOpenAI | None = None
        if provider.use_proxy:
            proxy_url = get_proxy_url(self._config)
            if proxy_url:
                proxy_client = build_proxy_client(
                    proxy_url, provider.api_key, provider.base_url
                )
                kwargs["client"] = proxy_client

        start = time.monotonic()
        try:
            try:
                resp = await acompletion(**kwargs)
            except Exception as e:
                if (
                    proxy_client is not None
                    and fallback_direct_enabled(self._config)
                    and is_conn_error(e)
                ):
                    log.warning("测试连接代理失败，回退直连: %s", e)
                    kwargs.pop("client", None)
                    resp = await acompletion(**kwargs)
                else:
                    raise
        except Exception as e:
            raise ValueError(f"连接失败: {e}") from e
        finally:
            if proxy_client is not None:
                await close_proxy_client(proxy_client)

        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "model": getattr(resp, "model", None) or model,
        }

    # ─── 辅助 ─────────────────────────────────────────────

    @staticmethod
    def _mask_provider(provider: ModelProvider) -> dict[str, Any]:
        """api_key 掩码输出。"""
        data = provider.model_dump()
        if data.get("api_key"):
            data["api_key"] = MASK
        return data
