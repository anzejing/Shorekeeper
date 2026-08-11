"""web_search 工具测试。

通过 mock aiohttp 模拟各服务商 API 响应，不依赖真实网络。
"""

from __future__ import annotations

import json
from typing import Any, Callable

import aiohttp
import pytest
import yaml

from app.config.service import ConfigService
from app.runtime.models import ToolCall
from app.tools import web_search as ws
from app.tools.web_search import (
    WEB_SEARCH_TOOL,
    WebSearchExecutor,
    SearchProvider,
)


# ─── Mock HTTP 基础设施 ───────────────────────────────────


class FakeResponse:
    """模拟 aiohttp 响应。"""

    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return json.dumps(self._payload)


class FakeSession:
    """模拟 aiohttp.ClientSession。

    注意：真实 aiohttp 的 session.get()/post() 返回上下文管理器对象（非协程），
    因此这里必须是同步方法直接返回 FakeResponse。
    """

    def __init__(self, handler: Callable) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self._handler("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self._handler("POST", url, **kwargs)


def make_session_factory(handler: Callable) -> Callable:
    """构造 aiohttp.ClientSession 的替换工厂。"""

    def factory(*args: Any, **kwargs: Any) -> FakeSession:
        return FakeSession(handler)

    return factory


# ─── 各服务商假响应 ───────────────────────────────────────

BRAVE_OK = {
    "web": {
        "results": [
            {
                "title": "Brave 搜索结果",
                "url": "https://example.com/1",
                "description": "这是 Brave 返回的摘要",
            },
        ]
    }
}

TAVILY_OK = {
    "results": [
        {
            "title": "Tavily 搜索结果",
            "url": "https://example.com/2",
            "content": "这是 Tavily 返回的摘要",
            "score": 0.9,
        },
    ]
}

FIRECRAWL_OK = {
    "data": [
        {
            "metadata": {
                "title": "Firecrawl 搜索结果",
                "sourceURL": "https://example.com/3",
            },
            "markdown": "这是 Firecrawl 返回的摘要",
        },
    ]
}

JINA_OK = {
    "data": [
        {
            "title": "Jina 搜索结果",
            "url": "https://example.com/4",
            "content": "这是 Jina 返回的摘要",
        },
    ]
}

TAVILY_EXTRACT_OK = {
    "results": [
        {
            "url": "https://example.com/page",
            "title": "提取的标题",
            "raw_content": "这是提取的正文内容",
        },
    ]
}


# ─── Fixtures / 辅助 ──────────────────────────────────────


@pytest.fixture
def executor(tmp_path, monkeypatch):
    """构造一个指定 API Key 的执行器（config.yaml 方式）。"""

    def _make(api_keys: dict[str, str] | None = None, priority: str = "brave,tavily,firecrawl,jina") -> WebSearchExecutor:
        cfg_data = {"search": {"priority": priority}}
        for name in ["brave", "tavily", "firecrawl", "jina"]:
            cfg_data["search"][f"{name}_api_key"] = (api_keys or {}).get(name, "")
        (tmp_path / "config.yaml").write_text(
            yaml.dump(cfg_data, allow_unicode=True), encoding="utf-8"
        )
        svc = ConfigService(data_dir=tmp_path)
        return WebSearchExecutor(svc)

    # 隔离 pi-search 兜底，避免读取真实配置干扰测试
    monkeypatch.setattr(ws, "_load_pi_search_keys", lambda: {})
    # 清除环境变量中的真实 API Key，避免泄漏到测试
    for env_key in ["BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY", "JINA_API_KEY"]:
        monkeypatch.delenv(env_key, raising=False)
    return _make


@pytest.fixture
def mock_http(monkeypatch):
    """按 URL 分发响应（返回 500 则视为服务商失败）。"""

    def _install(routes: dict[str, Any]) -> FakeSession:
        def handler(method: str, url: str, **kwargs: Any) -> FakeResponse:
            for prefix, payload in routes.items():
                if url.startswith(prefix):
                    if isinstance(payload, int):
                        return FakeResponse(payload)
                    return FakeResponse(200, payload)
            return FakeResponse(404, {"error": "no route"})

        factory = make_session_factory(handler)
        session = FakeSession(handler)
        monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: session)
        return session

    return _install


def make_call(**arguments: Any) -> ToolCall:
    return ToolCall(
        tool_call_id="call_1",
        tool_name="web_search",
        arguments=arguments,
    )


def text_of(result) -> str:
    return result.content[0].text


ALL_KEYS = {"brave": "k-brave", "tavily": "k-tavily", "firecrawl": "k-firecrawl", "jina": "k-jina"}


# ─── 配置解析 ─────────────────────────────────────────────


class TestConfigResolution:
    def test_config_yaml_takes_priority_over_env(self, executor, monkeypatch):
        """config.yaml 中的 key 优先于环境变量。"""
        ex = executor({"brave": "cfg-key"})
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "env-key")

        providers = ex._build_providers()
        assert [p.name for p in providers] == ["brave"]
        assert providers[0].api_key == "cfg-key"

    def test_env_var_fallback(self, executor, monkeypatch):
        """config.yaml 无 key 时使用环境变量。"""
        ex = executor({})
        monkeypatch.setenv("TAVILY_API_KEY", "env-key")

        providers = ex._build_providers()
        assert [p.name for p in providers] == ["tavily"]
        assert providers[0].api_key == "env-key"

    def test_pi_search_fallback(self, executor, monkeypatch):
        """config.yaml 和环境变量都无 key 时，读取 pi-search 配置兜底。"""
        monkeypatch.setattr(ws, "_load_pi_search_keys", lambda: {"jina": "pi-key"})
        ex = executor({})

        providers = ex._build_providers()
        assert [p.name for p in providers] == ["jina"]
        assert providers[0].api_key == "pi-key"

    def test_no_key_means_no_provider(self, executor):
        """全部无 key → 无可用服务商。"""
        ex = executor({})
        assert ex._build_providers() == []

    def test_priority_order(self, executor):
        """按配置的 priority 排序。"""
        ex = executor(ALL_KEYS, priority="jina,tavily")
        assert [p.name for p in ex._build_providers()] == ["jina", "tavily", "brave", "firecrawl"]


# ─── 基本执行 ─────────────────────────────────────────────


class TestExecutorBasics:
    @pytest.mark.asyncio
    async def test_help(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(make_call(action="help"))
        assert not result.is_error
        assert "search" in text_of(result)
        assert "extract" in text_of(result)

    @pytest.mark.asyncio
    async def test_unknown_action(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(make_call(action="foo"))
        assert result.is_error
        assert "未知 action" in text_of(result)

    @pytest.mark.asyncio
    async def test_search_missing_query(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(make_call(action="search"))
        assert result.is_error
        assert "query" in text_of(result)

    @pytest.mark.asyncio
    async def test_no_provider_error(self, executor):
        ex = executor({})
        result = await ex.execute(make_call(action="search", query="test"))
        assert result.is_error
        assert "API Key" in text_of(result)

    @pytest.mark.asyncio
    async def test_invalid_provider(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(
            make_call(action="search", query="test", provider="nonexistent")
        )
        assert result.is_error
        assert "未配置或不可用" in text_of(result)


# ─── search ───────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_brave_success(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="brave")
        session = mock_http({"https://api.search.brave.com": BRAVE_OK})

        result = await ex.execute(make_call(action="search", query="测试搜索"))

        assert not result.is_error
        text = text_of(result)
        assert "Brave 搜索结果" in text
        assert "https://example.com/1" in text
        # 请求参数正确
        _, url, kwargs = session.calls[0]
        assert kwargs["params"]["q"] == "测试搜索"
        assert kwargs["params"]["count"] == 10

    @pytest.mark.asyncio
    async def test_tavily_success(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="tavily")
        mock_http({"https://api.tavily.com": TAVILY_OK})

        result = await ex.execute(make_call(action="search", query="test"))

        assert not result.is_error
        text = text_of(result)
        assert "Tavily 搜索结果" in text
        assert "https://example.com/2" in text

    @pytest.mark.asyncio
    async def test_firecrawl_success(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="firecrawl")
        mock_http({"https://api.firecrawl.dev": FIRECRAWL_OK})

        result = await ex.execute(make_call(action="search", query="test"))

        assert not result.is_error
        assert "Firecrawl 搜索结果" in text_of(result)

    @pytest.mark.asyncio
    async def test_jina_success(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="jina")
        mock_http({"https://s.jina.ai": JINA_OK})

        result = await ex.execute(make_call(action="search", query="test"))

        assert not result.is_error
        assert "Jina 搜索结果" in text_of(result)

    @pytest.mark.asyncio
    async def test_failover_priority(self, executor, mock_http):
        """第一个服务商失败 → 自动回退到下一个。"""
        ex = executor(ALL_KEYS, priority="brave,tavily")
        mock_http({
            "https://api.search.brave.com": 500,
            "https://api.tavily.com": TAVILY_OK,
        })

        result = await ex.execute(make_call(action="search", query="test"))

        assert not result.is_error
        assert "Tavily 搜索结果" in text_of(result)

    @pytest.mark.asyncio
    async def test_failover_specified_provider(self, executor, mock_http):
        """指定服务商失败 → 仍回退到其他服务商。"""
        ex = executor(ALL_KEYS, priority="brave,tavily")
        mock_http({
            "https://api.search.brave.com": 500,
            "https://api.tavily.com": TAVILY_OK,
        })

        result = await ex.execute(
            make_call(action="search", query="test", provider="brave")
        )

        assert not result.is_error
        assert "Tavily 搜索结果" in text_of(result)

    @pytest.mark.asyncio
    async def test_all_fail(self, executor, mock_http):
        """所有服务商失败 → 明确错误。"""
        ex = executor(ALL_KEYS, priority="brave,tavily")
        mock_http({
            "https://api.search.brave.com": 500,
            "https://api.tavily.com": 500,
        })

        result = await ex.execute(make_call(action="search", query="test"))

        assert result.is_error
        text = text_of(result)
        assert "都失败" in text
        assert "brave" in text and "tavily" in text

    @pytest.mark.asyncio
    async def test_snippet_truncation(self, executor, mock_http):
        """长摘要截断到 _SNIPPET_LIMIT。"""
        long_desc = "长" * 500
        mock_http({
            "https://api.search.brave.com": {
                "web": {"results": [{"title": "t", "url": "https://e.com", "description": long_desc}]},
            }
        })
        ex = executor(ALL_KEYS, priority="brave")

        result = await ex.execute(make_call(action="search", query="test"))

        assert not result.is_error
        text = text_of(result)
        assert "…" in text
        assert len(text) < 500 + 100  # 截断生效


# ─── extract ──────────────────────────────────────────────


class TestExtract:
    @pytest.mark.asyncio
    async def test_missing_url(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(make_call(action="extract"))
        assert result.is_error
        assert "url" in text_of(result)

    @pytest.mark.asyncio
    async def test_invalid_url(self, executor):
        ex = executor(ALL_KEYS)
        result = await ex.execute(make_call(action="extract", url="ftp://x.com"))
        assert result.is_error
        assert "http" in text_of(result)

    @pytest.mark.asyncio
    async def test_tavily_extract_success(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="tavily")
        mock_http({"https://api.tavily.com/extract": TAVILY_EXTRACT_OK})

        result = await ex.execute(
            make_call(action="extract", url="https://example.com/page")
        )

        assert not result.is_error
        text = text_of(result)
        assert "提取的标题" in text
        assert "提取的正文内容" in text

    @pytest.mark.asyncio
    async def test_brave_not_used_for_extract(self, executor, mock_http):
        """Brave 不支持 extract，即使 priority 第一也会跳过。"""
        ex = executor(ALL_KEYS, priority="brave,tavily")
        session = mock_http({"https://api.tavily.com/extract": TAVILY_EXTRACT_OK})

        result = await ex.execute(
            make_call(action="extract", url="https://example.com/page")
        )

        assert not result.is_error
        # 只调用了 tavily，没有调用 brave
        assert all("brave" not in url for _, url, _ in session.calls)

    @pytest.mark.asyncio
    async def test_extract_all_fail(self, executor, mock_http):
        ex = executor(ALL_KEYS, priority="tavily")
        mock_http({"https://api.tavily.com": 500})

        result = await ex.execute(
            make_call(action="extract", url="https://example.com/page")
        )

        assert result.is_error
        assert "提取服务商" in text_of(result)


# ─── 集成：注册 + ToolIndex ───────────────────────────────


class TestIntegration:
    @pytest.mark.asyncio
    async def test_tool_definition_registered(self, executor, mock_http):
        """web_search 注册后可通过 tool_search 检索到。"""
        from app.tool.index import ToolIndex, ToolIndexEntry
        from app.tool.registry import ToolRegistry
        from app.tool.search import ToolSearchExecutor

        registry = ToolRegistry()
        ex = executor(ALL_KEYS)
        registry.register(WEB_SEARCH_TOOL, ex)

        # ToolIndex 收录（渐进式披露）
        index = ToolIndex()
        for td in registry.get_all_tools():
            index.add(ToolIndexEntry(
                name=td.name, description=td.description,
                parameters=td.parameters, category="core", source="builtin",
            ))

        hits = index.search("搜索网络网页")
        assert any(h.name == "web_search" for h in hits)

        # 实际调用 tool_search 执行器
        search_ex = ToolSearchExecutor(index)
        result = await search_ex.execute(ToolCall(
            tool_call_id="c2", tool_name="tool_search",
            arguments={"query": "搜索网页"},
        ))
        assert "web_search" in text_of(result)

    @pytest.mark.asyncio
    async def test_provider_class_map(self):
        """所有服务商类均可实例化。"""
        for name, cls in ws._PROVIDER_CLASSES.items():
            provider = cls("key", timeout=5.0)
            assert isinstance(provider, SearchProvider)
            assert provider.name == name
