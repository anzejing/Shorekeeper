"""代理配置模块测试。

覆盖：
- ProxyConfig 解析与设置页展示（secret 掩码）
- is_conn_error 错误分类
- models.dev 同步：代理传参 / 代理失败回退直连 / fallback 关闭时不回退
- provider /models 同步：use_proxy 传参 / 代理失败回退
- resolve_model 透传 use_proxy
- store use_proxy CRUD + 旧库迁移
- web_search 服务商代理参数透传
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp
import pytest
import yaml
from pytest_asyncio import fixture as asyncio_fixture

from app.config.meta import build_config_items
from app.config.schema import AppConfig
from app.config.service import ConfigService
from app.models_config.service import ModelConfigService
from app.models_config.store import ModelConfigStore, init_models_config_db
from app.net import proxy as proxy_mod
from app.runtime.store import init_db

# 模块内所有异步测试（pytest-asyncio strict 模式）
pytestmark = pytest.mark.asyncio


async def _real_conn_error() -> aiohttp.ClientConnectorError:
    """通过真实连接本地不可达端口产生 ClientConnectorError。"""
    async with aiohttp.ClientSession() as session:
        try:
            await session.get(
                "http://127.0.0.1:1",
                timeout=aiohttp.ClientTimeout(total=2),
            )
        except aiohttp.ClientConnectorError as e:
            return e
    raise AssertionError("预期产生连接错误")


# ─── ProxyConfig 解析与展示 ───────────────────────────────


class TestProxyConfig:
    def test_defaults(self) -> None:
        """默认值：enabled=False, fallback_direct=True。"""
        cfg = AppConfig()
        assert cfg.proxy.enabled is False
        assert cfg.proxy.url == ""
        assert cfg.proxy.fallback_direct is True
        assert cfg.proxy.timeout == 10.0

    def test_config_items_secret_mask(self, tmp_path: Path) -> None:
        """设置页展示：url 标记 secret 掩码显示。"""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {"proxy": {"enabled": True, "url": "http://user:pass@127.0.0.1:7890"}},
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        svc = ConfigService(data_dir=tmp_path)
        groups = build_config_items(svc.config)
        proxy_group = next(g for g in groups if g["group"] == "代理")
        items = {i["key"]: i for i in proxy_group["items"]}
        assert items["proxy.enabled"]["value"] is True
        # secret 字段掩码
        assert items["proxy.url"]["secret"] is True
        assert items["proxy.url"]["value"] == "***"

    def test_get_proxy_url_enabled_gate(self, tmp_path: Path) -> None:
        """get_proxy_url：开关关闭返回 None，开启返回 url。"""
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"proxy": {"enabled": False, "url": "http://127.0.0.1:7890"}}),
            encoding="utf-8",
        )
        svc = ConfigService(data_dir=tmp_path)
        assert proxy_mod.get_proxy_url(svc) is None
        svc.config.proxy.enabled = True
        assert proxy_mod.get_proxy_url(svc) == "http://127.0.0.1:7890"

    def test_fallback_direct_flag(self, tmp_path: Path) -> None:
        """fallback_direct 开关读取。"""
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"proxy": {"enabled": True, "fallback_direct": False}}),
            encoding="utf-8",
        )
        svc = ConfigService(data_dir=tmp_path)
        assert proxy_mod.fallback_direct_enabled(svc) is False


# ─── is_conn_error 分类 ───────────────────────────────────


class TestIsConnError:
    async def test_connector_error_is_conn(self) -> None:
        """aiohttp 连接错误 → True。"""
        err = await _real_conn_error()
        assert proxy_mod.is_conn_error(err)

    def test_http_status_error_not_conn(self) -> None:
        """业务 HTTP 错误（4xx/5xx 响应）→ False。"""
        class _ReqInfo:
            real_url = "http://example.com/x"

        err = aiohttp.ClientResponseError(
            request_info=_ReqInfo(), history=(), status=500, message="Server error"
        )
        assert not proxy_mod.is_conn_error(err)

    def test_timeout_is_conn(self) -> None:
        """超时 → True。"""
        assert proxy_mod.is_conn_error(asyncio.TimeoutError())

    def test_ssl_error_is_conn(self) -> None:
        """TLS 错误 → True。"""
        import ssl

        assert proxy_mod.is_conn_error(ssl.SSLError("handshake failed"))

    def test_plain_value_error_not_conn(self) -> None:
        """普通业务异常 → False。"""
        assert not proxy_mod.is_conn_error(ValueError("invalid request"))

    def test_litellm_connection_error_wrapped(self) -> None:
        """litellm 包装连接错误（含 Connection error 消息）→ True。"""
        class _FakeError(Exception):
            pass

        assert proxy_mod.is_conn_error(_FakeError("Connection error. retry later"))


# ─── models.dev 同步（代理 + fallback）────────────────────


class TestCatalogProxy:
    @asyncio_fixture
    async def service(self, tmp_path: Path):
        """ModelConfigService + 代理配置。"""
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"proxy": {"enabled": True, "url": "http://127.0.0.1:7890"}}),
            encoding="utf-8",
        )
        cfg = ConfigService(data_dir=tmp_path)
        db = await init_db()
        await init_models_config_db(db)
        return ModelConfigService(ModelConfigStore(db), tmp_path, config_service=cfg)

    async def test_sync_catalog_uses_proxy(self, service, monkeypatch) -> None:
        """fetch_catalog 收到代理参数。"""
        seen: dict[str, Any] = {}

        async def fake_fetch(
            etag: str = "",
            *,
            timeout: float = 120.0,
            proxy_url: str | None = None,
            fallback_direct: bool = True,
        ):
            seen["proxy_url"] = proxy_url
            seen["fallback_direct"] = fallback_direct
            return None, "etag", "", False  # 304 unchanged

        monkeypatch.setattr(
            "app.models_config.service.fetch_catalog", fake_fetch
        )
        await service.sync_catalog()
        assert seen["proxy_url"] == "http://127.0.0.1:7890"
        assert seen["fallback_direct"] is True

    async def test_sync_catalog_proxy_disabled(self, tmp_path: Path, monkeypatch) -> None:
        """代理开关关闭 → 不传代理。"""
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"proxy": {"enabled": False, "url": "http://127.0.0.1:7890"}}),
            encoding="utf-8",
        )
        cfg = ConfigService(data_dir=tmp_path)
        db = await init_db()
        await init_models_config_db(db)
        svc = ModelConfigService(ModelConfigStore(db), tmp_path, config_service=cfg)

        seen: dict[str, Any] = {}

        async def fake_fetch(etag="", *, timeout=120.0, proxy_url=None, fallback_direct=True):
            seen["proxy_url"] = proxy_url
            return None, "etag", "", False

        monkeypatch.setattr("app.models_config.service.fetch_catalog", fake_fetch)
        await svc.sync_catalog()
        assert seen["proxy_url"] is None

    async def test_fetch_catalog_proxy_fallback(self, monkeypatch) -> None:
        """代理连接失败 → 自动回退直连重试。"""
        from app.models_config.sync_models_dev import fetch_catalog

        # 先取真实连接错误（此时 ClientSession 尚未被 mock）
        real_err = await _real_conn_error()

        class _FakeResp:
            async def __aenter__(self):
                raise real_err

            async def __aexit__(self, *a):
                return None

        mod_instances: list[Any] = []

        class _FakeSession:
            def __init__(self):
                self.calls: list[str | None] = []
                mod_instances.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            def get(self, url, **kwargs):
                self.calls.append(kwargs.get("proxy"))
                return _FakeResp()

        monkeypatch.setattr("aiohttp.ClientSession", _FakeSession)
        with pytest.raises(aiohttp.ClientConnectorError):
            await fetch_catalog(proxy_url="http://127.0.0.1:1", fallback_direct=True)
        # 第一次走代理，回退后直连（proxy=None）
        assert [s.calls[0] for s in mod_instances] == [
            "http://127.0.0.1:1", None
        ]

    async def test_fetch_catalog_proxy_no_fallback(self, monkeypatch) -> None:
        """fallback 关闭 → 代理失败直接抛错，不回退。"""
        from app.models_config.sync_models_dev import fetch_catalog

        real_err = await _real_conn_error()

        class _FakeResp:
            async def __aenter__(self):
                raise real_err

            async def __aexit__(self, *a):
                return None

        mod_instances: list[Any] = []

        class _FakeSession:
            def __init__(self):
                self.calls: list[str | None] = []
                mod_instances.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            def get(self, url, **kwargs):
                self.calls.append(kwargs.get("proxy"))
                return _FakeResp()

        monkeypatch.setattr("aiohttp.ClientSession", _FakeSession)
        with pytest.raises(aiohttp.ClientConnectorError):
            await fetch_catalog(proxy_url="http://127.0.0.1:1", fallback_direct=False)
        assert [s.calls[0] for s in mod_instances] == ["http://127.0.0.1:1"]


# ─── provider /models 同步（use_proxy）───────────────────


class TestProviderSyncProxy:
    @asyncio_fixture
    async def service(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"proxy": {"enabled": True, "url": "http://127.0.0.1:7890"}}),
            encoding="utf-8",
        )
        cfg = ConfigService(data_dir=tmp_path)
        db = await init_db()
        await init_models_config_db(db)
        return ModelConfigService(ModelConfigStore(db), tmp_path, config_service=cfg)

    async def test_sync_uses_proxy_when_use_proxy(self, service, monkeypatch) -> None:
        """use_proxy=true → fetch_provider_models 传代理。"""
        await service.create_provider(
            {"provider_id": "p1", "name": "P1", "kind": "openai_like",
             "base_url": "https://x/v1", "api_key": "sk-1", "use_proxy": True}
        )
        seen: dict[str, Any] = {}

        async def fake_fetch(provider, *, models_url=None, timeout=30.0, proxy_url=None, fallback_direct=True):
            seen["proxy_url"] = proxy_url
            return [{"id": "m1", "display_name": "M1"}]

        monkeypatch.setattr("app.models_config.service.fetch_provider_models", fake_fetch)
        await service.sync_provider_models("p1")
        assert seen["proxy_url"] == "http://127.0.0.1:7890"

    async def test_sync_no_proxy_when_not_use_proxy(self, service, monkeypatch) -> None:
        """use_proxy=false（默认）→ 不传代理。"""
        await service.create_provider(
            {"provider_id": "p2", "name": "P2", "kind": "openai_like",
             "base_url": "https://x/v1", "api_key": "sk-2"}
        )
        seen: dict[str, Any] = {}

        async def fake_fetch(provider, *, models_url=None, timeout=30.0, proxy_url=None, fallback_direct=True):
            seen["proxy_url"] = proxy_url
            return [{"id": "m1", "display_name": "M1"}]

        monkeypatch.setattr("app.models_config.service.fetch_provider_models", fake_fetch)
        await service.sync_provider_models("p2")
        assert seen["proxy_url"] is None


# ─── resolve_model 透传 use_proxy ────────────────────────


class TestResolveModelProxy:
    @asyncio_fixture
    async def service(self, tmp_path: Path):
        db = await init_db()
        await init_models_config_db(db)
        return ModelConfigService(ModelConfigStore(db), tmp_path)

    async def test_resolve_model_carries_use_proxy(self, service) -> None:
        """resolve_model 返回的 llm_extra 含 use_proxy。"""
        await service.create_provider(
            {"provider_id": "p3", "name": "P3", "kind": "openai_like",
             "base_url": "https://x/v1", "api_key": "sk-3", "use_proxy": True}
        )
        await service.add_model("p3", "m1")
        resolved = await service.resolve_model("p3", "m1")
        assert resolved["llm_extra"]["use_proxy"] is True

    async def test_resolve_model_use_proxy_default_false(self, service) -> None:
        """未开启走代理 → use_proxy=False。"""
        await service.create_provider(
            {"provider_id": "p4", "name": "P4", "kind": "openai_like",
             "base_url": "https://x/v1", "api_key": "sk-4"}
        )
        await service.add_model("p4", "m1")
        resolved = await service.resolve_model("p4", "m1")
        assert resolved["llm_extra"]["use_proxy"] is False


# ─── store use_proxy CRUD + 迁移 ─────────────────────────


class TestStoreProxy:
    @asyncio_fixture
    async def store(self, tmp_path: Path):
        db = await init_db()
        await init_models_config_db(db)
        return ModelConfigStore(db)

    async def test_create_update_use_proxy(self, store) -> None:
        """create/update 持久化 use_proxy。"""
        from app.models_config.schema import ModelProvider

        p = ModelProvider(
            provider_id="sp1", name="SP1", kind="openai_like",
            base_url="https://x/v1", api_key="sk-1", use_proxy=True,
        )
        await store.create_provider(p)
        got = await store.get_provider("sp1")
        assert got.use_proxy is True

        p2 = p.model_copy(update={"use_proxy": False})
        await store.update_provider(p2)
        got2 = await store.get_provider("sp1")
        assert got2.use_proxy is False

    async def test_migrate_old_db_adds_column(self) -> None:
        """旧库无 use_proxy 列 → 迁移自动添加并返回默认 False。"""
        import aiosqlite

        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        # 模拟旧表（无 use_proxy 列）+ 旧数据
        await db.executescript(
            "CREATE TABLE model_providers ("
            " provider_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,"
            " base_url TEXT NOT NULL DEFAULT '', api_key TEXT NOT NULL DEFAULT '',"
            " enabled INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL DEFAULT 'custom',"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
            "INSERT INTO model_providers VALUES ('old','O','openai','','',1,'custom','t','t');"
        )
        # 迁移
        await init_models_config_db(db)
        got = await ModelConfigStore(db).get_provider("old")
        assert got.use_proxy is False
        await db.close()


# ─── web_search 服务商代理透传 ───────────────────────────


class TestWebSearchProxy:
    def test_provider_gets_proxy_params(self, tmp_path: Path) -> None:
        """代理开启时服务商收到 proxy_url。"""
        from app.tools.web_search import BraveProvider

        p = BraveProvider("key", 30.0, "http://127.0.0.1:7890", True)
        assert p.proxy_url == "http://127.0.0.1:7890"
        assert p.fallback_direct is True

    def test_provider_no_proxy_default(self) -> None:
        """未配置代理 → proxy_url 为 None。"""
        from app.tools.web_search import BraveProvider

        p = BraveProvider("key")
        assert p.proxy_url is None
