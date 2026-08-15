"""模型配置模块测试。

覆盖：Provider CRUD（掩码/校验）、模型管理、当前模型（可空可删）、
models.dev 目录同步（ETag 增量）、provider /models 端点同步、
测试连接（mock litellm）、删除 provider 自动清空当前模型。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_asyncio import fixture as asyncio_fixture
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.models import init_models_api, router as models_router
from app.models_config.litellm_mapping import build_litellm_name
from app.models_config.service import ModelConfigService
from app.models_config.store import ModelConfigStore, init_models_config_db
from app.runtime.store import init_db


# ─── Fixtures ─────────────────────────────────────────────


@asyncio_fixture
async def service(tmp_path: Path):
    """创建 ModelConfigService（内存 DB + 临时数据目录）。"""
    db = await init_db()
    await init_models_config_db(db)
    svc = ModelConfigService(ModelConfigStore(db), tmp_path)
    return svc


@asyncio_fixture
async def app(service: ModelConfigService):
    """FastAPI 测试 app。"""
    init_models_api(service)
    test_app = FastAPI()
    test_app.include_router(models_router)
    return test_app


async def _create_provider(svc: ModelConfigService, **overrides: Any) -> None:
    """创建测试 provider。"""
    data = {
        "provider_id": "test-provider",
        "name": "Test Provider",
        "kind": "openai_like",
        "base_url": "https://test.local/v1",
        "api_key": "sk-test",
        **overrides,
    }
    await svc.create_provider(data)


# ─── Provider CRUD ────────────────────────────────────────


class TestProviderCRUD:
    @pytest.mark.asyncio
    async def test_create_and_list_masks_key(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={
                    "provider_id": "opencode",
                    "name": "OpenCode",
                    "kind": "openai_like",
                    "base_url": "https://opencode.ai/zen/go/v1",
                    "api_key": "sk-secret",
                },
            )
            assert resp.status_code == 201

            resp = await client.get("/api/models/providers")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["provider_id"] == "opencode"
            assert data[0]["api_key"] == "***"

    @pytest.mark.asyncio
    async def test_create_invalid_kind(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={
                    "provider_id": "bad",
                    "kind": "unknown",
                    "api_key": "sk-x",
                },
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_openai_like_requires_base_url(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={"provider_id": "bad", "kind": "openai_like", "api_key": "sk-x"},
            )
            assert resp.status_code == 422
            assert "base_url" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_keeps_masked_api_key(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # api_key 回传掩码 → 保留原值
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"name": "Renamed", "api_key": "***"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Renamed"

        provider = await service._store.get_provider("test-provider")
        assert provider.api_key == "sk-test"  # 原 key 未被覆盖

    @pytest.mark.asyncio
    async def test_update_with_new_api_key(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"api_key": "sk-new"},
            )
            assert resp.status_code == 200

        provider = await service._store.get_provider("test-provider")
        assert provider.api_key == "sk-new"

    @pytest.mark.asyncio
    async def test_delete_provider_clears_current_model(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.set_current("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/models/providers/test-provider")
            assert resp.status_code == 200

            # 当前模型已清空
            current = await client.get("/api/models/current")
            assert current.status_code == 200
            assert current.json() is None


# ─── 模型管理 ─────────────────────────────────────────────


class TestModels:
    @pytest.mark.asyncio
    async def test_add_and_list_models(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/test-provider/models",
                json={"model_id": "deepseek-v4-flash"},
            )
            assert resp.status_code == 201
            assert resp.json()["litellm_name"] == "openai/deepseek-v4-flash"

            resp = await client.get("/api/models/providers/test-provider/models")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_remove_current_model_clears(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.add_model("test-provider", "model-b")
        await service.set_current("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(
                "/api/models/providers/test-provider/models/model-a"
            )
            assert resp.status_code == 200

            current = await client.get("/api/models/current")
            assert current.json() is None


# ─── 全局当前模型 ─────────────────────────────────────────


class TestCurrentModel:
    @pytest.mark.asyncio
    async def test_current_null_by_default(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/models/current")
            assert resp.status_code == 200
            assert resp.json() is None

    @pytest.mark.asyncio
    async def test_set_and_get_current(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/current",
                json={"provider_id": "test-provider", "model_id": "model-a"},
            )
            assert resp.status_code == 200
            assert resp.json()["litellm_name"] == "openai/model-a"

            resp = await client.get("/api/models/current")
            assert resp.json()["model_id"] == "model-a"

    @pytest.mark.asyncio
    async def test_set_current_not_found(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/current",
                json={"provider_id": "nope", "model_id": "nope"},
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_current(self, service: ModelConfigService, app: FastAPI) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.set_current("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/api/models/current")
            assert resp.status_code == 200

            resp = await client.get("/api/models/current")
            assert resp.json() is None


# ─── models.dev 目录同步 ──────────────────────────────────


class TestCatalogSync:
    @pytest.mark.asyncio
    async def test_sync_catalog_unchanged_on_etag(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ETag 未变化 → 返回 unchanged。"""
        # 首次同步
        async def fake_fetch(
            etag: str = "",
            *,
            timeout: float = 120.0,
            proxy_url: str | None = None,
            fallback_direct: bool = True,
        ):
            return (
                {
                    "openai": {
                        "name": "OpenAI",
                        "npm": "@ai-sdk/openai",
                        "models": {
                            "gpt-4o": {"name": "GPT-4o", "last_updated": "2026-01-01"}
                        },
                    }
                },
                "etag-v2",
                "2026-01-01",
                True,
            )

        monkeypatch.setattr(
            "app.models_config.service.fetch_catalog", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/models/catalog/sync")
            assert resp.status_code == 200
            assert resp.json()["status"] == "updated"

        # 第二次：etag 命中 → 未变化
        async def fake_fetch_304(
            etag: str = "",
            *,
            timeout: float = 120.0,
            proxy_url: str | None = None,
            fallback_direct: bool = True,
        ):
            return None, etag, "", False

        monkeypatch.setattr(
            "app.models_config.service.fetch_catalog", fake_fetch_304
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/models/catalog/sync")
            assert resp.status_code == 200
            assert resp.json()["status"] == "unchanged"

    @pytest.mark.asyncio
    async def test_catalog_status_and_providers(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        catalog = {
            "openai": {
                "name": "OpenAI",
                "npm": "@ai-sdk/openai",
                "models": {"gpt-4o": {"name": "GPT-4o"}},
            },
            "deepseek": {
                "name": "DeepSeek",
                "npm": "@ai-sdk/openai-compatible",
                "api": "https://api.deepseek.com",
                "models": {"deepseek-v4-flash": {"name": "DeepSeek V4 Flash"}},
            },
        }
        # 写缓存文件
        (service._data_dir / "models_dev_catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/models/catalog/status")
            assert resp.status_code == 200
            assert resp.json()["has_cache"] is True

            resp = await client.get("/api/models/catalog/providers?search=deep")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["provider_id"] == "deepseek"
            assert data[0]["kind"] == "openai_like"
            assert data[0]["api"] == "https://api.deepseek.com"

    @pytest.mark.asyncio
    async def test_import_catalog_provider_prefills_models(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """目录导入：source=catalog + model_ids → 按需预填模型（含元数据）。"""
        catalog = {
            "zhipuai": {
                "name": "Zhipu AI",
                "npm": "@ai-sdk/openai-compatible",
                "api": "https://open.bigmodel.cn/api/paas/v4",
                "models": {
                    "glm-5": {"name": "GLM-5", "tool_call": True, "cost": {"input": 1}},
                    "glm-5.1": {"name": "GLM-5.1", "tool_call": True},
                },
            }
        }
        (service._data_dir / "models_dev_catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={
                    "provider_id": "zhipuai",
                    "name": "Zhipu AI",
                    "kind": "openai_like",
                    "api_key": "sk-zhipu",
                    "source": "catalog",
                    "model_ids": ["glm-5", "glm-5.1"],
                },
            )
            assert resp.status_code == 201

            resp = await client.get("/api/models/providers/zhipuai/models")
            assert resp.status_code == 200
            models = resp.json()
            assert len(models) == 2
            glm5 = next(m for m in models if m["model_id"] == "glm-5")
            assert glm5["meta_source"] == "models_dev"
            assert glm5["metadata"]["cost"]["input"] == 1  # 元数据保留（计量准备）
            assert glm5["litellm_name"] == "openai/glm-5"

    @pytest.mark.asyncio
    async def test_create_provider_without_model_ids_imports_none(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """缺省 model_ids → 不导入模型。"""
        catalog = {
            "zhipuai": {
                "name": "Zhipu AI",
                "npm": "@ai-sdk/openai-compatible",
                "api": "https://open.bigmodel.cn/api/paas/v4",
                "models": {"glm-5": {"name": "GLM-5"}},
            }
        }
        (service._data_dir / "models_dev_catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={
                    "provider_id": "zhipuai",
                    "kind": "openai_like",
                    "base_url": "https://open.bigmodel.cn/api/paas/v4",
                },
            )
            assert resp.status_code == 201
            resp = await client.get("/api/models/providers/zhipuai/models")
            assert resp.json() == []


# ─── provider /models 端点同步 ────────────────────────────


class TestProviderSync:
    @pytest.mark.asyncio
    async def test_sync_provider_models(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _create_provider(service)
        # 模拟 /models 端点返回
        async def fake_fetch(
            provider,
            *,
            models_url: str | None = None,
            timeout: float = 30.0,
            proxy_url: str | None = None,
            fallback_direct: bool = True,
        ):
            return [
                {"id": "deepseek-v4-flash", "display_name": "DeepSeek V4 Flash"},
                {"id": "deepseek-v4-pro", "display_name": "DeepSeek V4 Pro"},
            ]

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/models/providers/test-provider/sync")
            assert resp.status_code == 200
            assert resp.json()["count"] == 2

            resp = await client.get("/api/models/providers/test-provider/models")
            models = resp.json()
            assert len(models) == 2
            assert models[0]["litellm_name"] == "openai/deepseek-v4-flash"

    @pytest.mark.asyncio
    async def test_sync_provider_error(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _create_provider(service)

        async def fake_fetch(
            provider,
            *,
            models_url: str | None = None,
            timeout: float = 30.0,
            proxy_url: str | None = None,
            fallback_direct: bool = True,
        ):
            from app.models_config.sync_provider import ProviderSyncError

            raise ProviderSyncError("HTTP 401")

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/models/providers/test-provider/sync")
            assert resp.status_code == 422
            assert "401" in resp.json()["detail"]


# ─── 测试连接 ─────────────────────────────────────────────


class TestConnection:
    @pytest.mark.asyncio
    async def test_test_connection_ok(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")

        class FakeResp:
            model = "openai/model-a"

        async def fake_acompletion(**kwargs):
            assert kwargs["model"] == "openai/model-a"
            assert kwargs["api_base"] == "https://test.local/v1"
            assert kwargs["api_key"] == "sk-test"
            return FakeResp()

        monkeypatch.setattr("app.models_config.service.acompletion", fake_acompletion)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/test-provider/test",
                json={"model_id": "model-a"},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_test_connection_fails(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")

        async def fake_acompletion(**kwargs):
            raise RuntimeError("connection refused")

        monkeypatch.setattr("app.models_config.service.acompletion", fake_acompletion)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/test-provider/test",
                json={"model_id": "model-a"},
            )
            assert resp.status_code == 422
            assert "connection refused" in resp.json()["detail"]


# ─── litellm_name 生成 ────────────────────────────────────


class TestLitellmName:
    def test_all_kinds(self) -> None:
        assert build_litellm_name("openai", "gpt-4o") == "openai/gpt-4o"
        # openai 兼容端点也走 openai/ 前缀 + api_base（litellm 1.94.1 实测）
        assert build_litellm_name("openai_like", "deepseek-v4-flash") == "openai/deepseek-v4-flash"
        assert build_litellm_name("anthropic", "claude-x") == "anthropic/claude-x"
        assert build_litellm_name("gemini", "gemini-2.5-pro") == "gemini/gemini-2.5-pro"

    def test_invalid_kind(self) -> None:
        import pytest as _p

        with _p.raises(ValueError):
            build_litellm_name("unknown", "x")


# ─── 模型启用/隐藏（PR1） ─────────────────────────────────


class TestModelEnable:
    @pytest.mark.asyncio
    async def test_toggle_enabled(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider/models/model-a",
                json={"enabled": False},
            )
            assert resp.status_code == 200
            assert resp.json()["enabled"] is False

            resp = await client.get("/api/models/providers/test-provider/models")
            assert resp.json()[0]["enabled"] is False

            # 重新启用
            resp = await client.put(
                "/api/models/providers/test-provider/models/model-a",
                json={"enabled": True},
            )
            assert resp.json()["enabled"] is True

    @pytest.mark.asyncio
    async def test_hide_current_model_clears(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.set_current("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider/models/model-a",
                json={"enabled": False},
            )
            assert resp.status_code == 200

            current = await client.get("/api/models/current")
            assert current.json() is None

    @pytest.mark.asyncio
    async def test_toggle_not_found(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/nope/models/nope",
                json={"enabled": False},
            )
            assert resp.status_code == 404


# ─── 编辑 Provider：model_ids 启用集合（PR1） ─────────────


class TestUpdateModelIds:
    async def _setup(self, svc: ModelConfigService) -> None:
        await _create_provider(svc)
        await svc.add_model("test-provider", "model-a")
        await svc.add_model("test-provider", "model-b")

    @pytest.mark.asyncio
    async def test_model_ids_syncs_enabled_set(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """model_ids = 启用集合：未列出 → 隐藏（保留不删除）；新 id → 插入。"""
        await self._setup(service)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"model_ids": ["model-a", "model-new"]},
            )
            assert resp.status_code == 200

            resp = await client.get("/api/models/providers/test-provider/models")
            models = {m["model_id"]: m for m in resp.json()}
            assert set(models) == {"model-a", "model-b", "model-new"}
            assert models["model-a"]["enabled"] is True
            assert models["model-b"]["enabled"] is False  # 隐藏保留
            assert models["model-new"]["enabled"] is True  # 新 id 插入

    @pytest.mark.asyncio
    async def test_model_ids_null_keeps_state(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """model_ids=null → 不动模型。"""
        await self._setup(service)
        await service.set_model_enabled("test-provider", "model-b", False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"name": "Renamed"},
            )
            assert resp.status_code == 200

        resp = await service.list_models("test-provider")
        state = {e.model_id: e.enabled for e in resp}
        assert state == {"model-a": True, "model-b": False}

    @pytest.mark.asyncio
    async def test_hide_current_model_via_update_clears(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """编辑把当前模型移出启用集合 → 清空 current。"""
        await self._setup(service)
        await service.set_current("test-provider", "model-a")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"model_ids": ["model-b"]},
            )
            assert resp.status_code == 200

            current = await client.get("/api/models/current")
            assert current.json() is None

    @pytest.mark.asyncio
    async def test_update_keeps_models_url(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """models_url 落库与更新。"""
        await _create_provider(service)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/providers/test-provider",
                json={"models_url": "https://custom.local/v1/models"},
            )
            assert resp.status_code == 200
            assert resp.json()["models_url"] == "https://custom.local/v1/models"

        provider = await service._store.get_provider("test-provider")
        assert provider.models_url == "https://custom.local/v1/models"

    @pytest.mark.asyncio
    async def test_create_stores_models_url(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers",
                json={
                    "provider_id": "custom",
                    "kind": "openai_like",
                    "base_url": "https://x.local/v1",
                    "models_url": "https://x.local/v1/models",
                },
            )
            assert resp.status_code == 201
            assert resp.json()["models_url"] == "https://x.local/v1/models"


# ─── 预览接口（PR1） ──────────────────────────────────────


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_returns_models(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(provider, **kwargs):
            # models_url 优先透传
            assert provider.models_url == "https://custom.local/v1/models"
            return [{"id": "m1", "display_name": "M1"}]

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/preview",
                json={
                    "kind": "openai_like",
                    "base_url": "https://custom.local/v1",
                    "models_url": "https://custom.local/v1/models",
                    "api_key": "sk-x",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["models"] == [{"id": "m1", "display_name": "M1"}]

    @pytest.mark.asyncio
    async def test_preview_derives_url_from_base(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(provider, **kwargs):
            # models_url 缺省 → 由 base_url 推导（openai 系 /models）
            assert provider.models_url == ""
            return [{"id": "m1", "display_name": "M1"}]

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/preview",
                json={"kind": "openai_like", "base_url": "https://x.local/v1"},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_preview_invalid_kind(self, app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/preview",
                json={"kind": "unknown"},
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_preview_error(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.models_config.sync_provider import ProviderSyncError

        async def fake_fetch(provider, **kwargs):
            raise ProviderSyncError("HTTP 401")

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/models/providers/preview",
                json={"kind": "openai_like", "base_url": "https://x.local/v1"},
            )
            assert resp.status_code == 422
            assert "401" in resp.json()["detail"]


# ─── 目录默认端点（PR1） ──────────────────────────────────


class TestCatalogDefaultBaseUrl:
    @pytest.mark.asyncio
    async def test_api_field_preferred(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """有 api 字段 → default_base_url 取 api。"""
        catalog = {
            "deepseek": {
                "name": "DeepSeek",
                "npm": "@ai-sdk/openai-compatible",
                "api": "https://api.deepseek.com",
                "models": {"deepseek-v4-flash": {"name": "DeepSeek V4 Flash"}},
            }
        }
        (service._data_dir / "models_dev_catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/models/catalog/providers?search=deep")
            data = resp.json()
            assert data[0]["default_base_url"] == "https://api.deepseek.com"

    @pytest.mark.asyncio
    async def test_kind_official_fallback(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        """无 api 字段 → 按 kind 官方端点兜底。"""
        catalog = {
            "openai": {
                "name": "OpenAI",
                "npm": "@ai-sdk/openai",
                "models": {"gpt-4o": {"name": "GPT-4o"}},
            },
            "anthropic": {
                "name": "Anthropic",
                "npm": "@ai-sdk/anthropic",
                "models": {"claude-x": {"name": "Claude X"}},
            },
        }
        (service._data_dir / "models_dev_catalog.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/models/catalog/providers")
            by_id = {p["provider_id"]: p for p in resp.json()}
            assert by_id["openai"]["default_base_url"] == "https://api.openai.com/v1"
            assert (
                by_id["anthropic"]["default_base_url"] == "https://api.anthropic.com"
            )


# ─── 禁用模型不可用（PR1） ────────────────────────────────


class TestDisabledModelEnforcement:
    @pytest.mark.asyncio
    async def test_resolve_rejects_disabled(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.set_model_enabled("test-provider", "model-a", False)

        with pytest.raises(ValueError, match="已禁用"):
            await service.resolve_model("test-provider", "model-a")

    @pytest.mark.asyncio
    async def test_set_current_rejects_disabled(
        self, service: ModelConfigService, app: FastAPI
    ) -> None:
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.set_model_enabled("test-provider", "model-a", False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/models/current",
                json={"provider_id": "test-provider", "model_id": "model-a"},
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_sync_preserves_hidden_state(
        self, service: ModelConfigService, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同步不重置隐藏状态。"""
        await _create_provider(service)
        await service.add_model("test-provider", "model-a")
        await service.add_model("test-provider", "model-b")
        await service.set_model_enabled("test-provider", "model-b", False)

        async def fake_fetch(provider, **kwargs):
            return [
                {"id": "model-a", "display_name": "A"},
                {"id": "model-b", "display_name": "B"},
                {"id": "model-c", "display_name": "C"},  # 新模型默认启用
            ]

        monkeypatch.setattr(
            "app.models_config.service.fetch_provider_models", fake_fetch
        )
        await service.sync_provider_models("test-provider")

        entries = await service.list_models("test-provider")
        state = {e.model_id: e.enabled for e in entries}
        assert state == {"model-a": True, "model-b": False, "model-c": True}
