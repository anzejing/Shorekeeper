"""web_search Tool — 统一网络搜索。

支持多个搜索服务商（Brave / Tavily / Firecrawl / Jina），
按配置优先级自动选择，指定服务商失败时自动回退到下一个可用服务商。

动作：
- search: 网页搜索（返回标题/URL/摘要）
- extract: 提取网页正文内容
- help: 返回使用指南（LLM 可自查用法）

API Key 解析优先级：config.yaml（search 段）→ 环境变量 → pi-search 配置兜底。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from app.config.service import ConfigService
from app.runtime.models import SideEffectLevel, TextPart, ToolCall, ToolDef, ToolResult

log = logging.getLogger(__name__)

# ─── 常量 ─────────────────────────────────────────────────

# 服务商名称（保持固定顺序，优先级由配置决定）
_PROVIDER_NAMES = ["brave", "tavily", "firecrawl", "jina"]

# 环境变量名（与 pi-search 保持一致）
_ENV_KEYS: dict[str, str] = {
    "brave": "BRAVE_SEARCH_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "jina": "JINA_API_KEY",
}

# pi-search 配置文件（只读兜底，仅文件存在时读取）
_PI_SEARCH_CONFIG_PATHS = [
    Path.home() / ".config" / "pi-search" / "config.json",
]

# 搜索结果摘要截断长度
_SNIPPET_LIMIT = 300
# 提取正文截断长度
_EXTRACT_LIMIT = 6000

# ─── 配置解析 ─────────────────────────────────────────────


def _load_pi_search_keys() -> dict[str, str]:
    """从 pi-search 配置读取 API Key（只读兜底，不修改该文件）。"""
    keys: dict[str, str] = {}
    for path in _PI_SEARCH_CONFIG_PATHS:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            providers = data.get("providers", {})
            for name in _PROVIDER_NAMES:
                provider = providers.get(name) or {}
                if provider.get("api_key"):
                    keys[name] = str(provider["api_key"])
        except Exception:
            log.warning("读取 pi-search 配置失败: %s", path)
        break  # 只取第一个存在的路径
    return keys


def _resolve_api_key(
    provider: str,
    search_cfg: Any,
    pi_keys: dict[str, str],
) -> str:
    """按优先级解析 API Key：config.yaml → 环境变量 → pi-search 配置。"""
    # 1. config.yaml（search 段）
    yaml_key = getattr(search_cfg, f"{provider}_api_key", "") or ""
    if yaml_key:
        return yaml_key

    # 2. 环境变量
    env_key = _ENV_KEYS.get(provider, "")
    if env_key:
        env_value = os.environ.get(env_key, "")
        if env_value:
            return env_value

    # 3. pi-search 配置兜底
    return pi_keys.get(provider, "")


# ─── 数据模型 ─────────────────────────────────────────────


@dataclass
class SearchResult:
    """单条搜索结果。"""

    title: str
    url: str
    content: str
    score: float = 0.0
    source: str = ""


@dataclass
class SearchResponse:
    """搜索响应。"""

    query: str
    results: list[SearchResult]
    response_time: float
    source: str


class SearchProvider:
    """搜索服务商基类。"""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.name = self.__class__.__name__.replace("Provider", "").lower()

    async def search(self, query: str, **kwargs: Any) -> SearchResponse:
        """执行搜索。"""
        raise NotImplementedError

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """提取网页正文。"""
        raise NotImplementedError


# ─── 服务商适配 ───────────────────────────────────────────


class BraveProvider(SearchProvider):
    """Brave Search 服务商（仅支持搜索）。"""

    BASE_URL = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        super().__init__(api_key, timeout)
        self.headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }

    async def search(self, query: str, **kwargs: Any) -> SearchResponse:
        start = time.time()
        max_results = min(int(kwargs.get("max_results", 10)), 20)
        params = {"q": query, "count": max_results}
        if kwargs.get("freshness"):
            params["freshness"] = kwargs["freshness"]
        if kwargs.get("country"):
            params["country"] = kwargs["country"]

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.BASE_URL}/web/search",
                headers=self.headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Brave API 错误: {response.status}")
                data = await response.json()

        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("description", ""),
                score=float(item.get("age", 0) or 0),
                source=self.name,
            )
            for item in data.get("web", {}).get("results", [])
        ]
        return SearchResponse(
            query=query,
            results=results,
            response_time=time.time() - start,
            source=self.name,
        )

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Brave Search 不支持内容提取")


class TavilyProvider(SearchProvider):
    """Tavily 服务商（搜索 + 提取）。"""

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        super().__init__(api_key, timeout)
        self.headers = {"Content-Type": "application/json"}

    async def search(self, query: str, **kwargs: Any) -> SearchResponse:
        start = time.time()
        max_results = min(int(kwargs.get("max_results", 10)), 20)
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": kwargs.get("search_depth", "basic"),
            "topic": kwargs.get("topic", "general"),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/search",
                headers=self.headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Tavily API 错误: {response.status}")
                data = await response.json()

        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=float(item.get("score", 0) or 0),
                source=self.name,
            )
            for item in data.get("results", [])
        ]
        return SearchResponse(
            query=query,
            results=results,
            response_time=time.time() - start,
            source=self.name,
        )

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "api_key": self.api_key,
            "urls": [url],
            "extract_depth": kwargs.get("extract_depth", "basic"),
            "format": kwargs.get("format", "markdown"),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/extract",
                headers=self.headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Tavily API 错误: {response.status}")
                data = await response.json()

        results = data.get("results", [])
        if results:
            return {
                "url": results[0].get("url", url),
                "title": results[0].get("title", ""),
                "content": results[0].get("raw_content", ""),
                "source": self.name,
            }
        return {"url": url, "title": "", "content": "", "source": self.name}


class FirecrawlProvider(SearchProvider):
    """Firecrawl 服务商（搜索 + 提取）。"""

    BASE_URL = "https://api.firecrawl.dev/v1"

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        super().__init__(api_key, timeout)
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def search(self, query: str, **kwargs: Any) -> SearchResponse:
        start = time.time()
        max_results = min(int(kwargs.get("max_results", 10)), 20)
        payload = {"query": query, "limit": max_results}
        if kwargs.get("include_domains"):
            payload["include_domains"] = kwargs["include_domains"]
        if kwargs.get("exclude_domains"):
            payload["exclude_domains"] = kwargs["exclude_domains"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/search",
                headers=self.headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Firecrawl API 错误: {response.status}")
                data = await response.json()

        results = []
        for item in data.get("data", []):
            metadata = item.get("metadata", {})
            results.append(SearchResult(
                title=metadata.get("title", ""),
                url=metadata.get("sourceURL", item.get("url", "")),
                content=item.get("markdown", item.get("content", "")),
                source=self.name,
            ))
        return SearchResponse(
            query=query,
            results=results,
            response_time=time.time() - start,
            source=self.name,
        )

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "url": url,
            "formats": [kwargs.get("format", "markdown")],
        }
        if kwargs.get("only_main_content"):
            payload["onlyMainContent"] = kwargs["only_main_content"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/scrape",
                headers=self.headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Firecrawl API 错误: {response.status}")
                data = await response.json()

        result = data.get("data", {})
        return {
            "url": url,
            "title": (result.get("metadata") or {}).get("title", ""),
            "content": result.get("markdown", result.get("content", "")),
            "source": self.name,
        }


class JinaProvider(SearchProvider):
    """Jina AI 服务商（搜索 + 提取）。"""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        super().__init__(api_key, timeout)
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    async def search(self, query: str, **kwargs: Any) -> SearchResponse:
        start = time.time()
        max_results = min(int(kwargs.get("max_results", 10)), 20)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://s.jina.ai/{query}",
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Jina API 错误: {response.status}")
                data = await response.json()

        results = []
        for item in data.get("data", []):
            if len(results) >= max_results:
                break
            metadata = item.get("metadata", {})
            results.append(SearchResult(
                title=item.get("title", metadata.get("title", "")),
                url=item.get("url", ""),
                content=item.get("content", item.get("description", "")),
                source=self.name,
            ))
        return SearchResponse(
            query=query,
            results=results,
            response_time=time.time() - start,
            source=self.name,
        )

    async def extract(self, url: str, **kwargs: Any) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://r.jina.ai/{url}",
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise Exception(f"Jina API 错误: {response.status}")
                data = await response.json()

        result = data.get("data", {})
        return {
            "url": url,
            "title": result.get("title", ""),
            "content": result.get("content", ""),
            "source": self.name,
        }


# 服务商类映射
_PROVIDER_CLASSES: dict[str, type[SearchProvider]] = {
    "brave": BraveProvider,
    "tavily": TavilyProvider,
    "firecrawl": FirecrawlProvider,
    "jina": JinaProvider,
}

# 支持 extract 动作的服务商（Brave 不支持）
_EXTRACT_PROVIDERS = {"tavily", "firecrawl", "jina"}


# ─── 工具定义 ─────────────────────────────────────────────

WEB_SEARCH_TOOL = ToolDef(
    name="web_search",
    description=(
        "网络搜索工具。可搜索网页（action=search）或提取网页正文（action=extract）。"
        "调用 action=help 可查看完整用法。"
        "支持 Brave/Tavily/Firecrawl/Jina 多个服务商，自动选择可用服务商，失败自动回退。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["help", "search", "extract"],
                "description": (
                    "操作类型。search=搜索网页（需提供 query）；"
                    "extract=提取网页正文（需提供 url）；help=查看使用指南。"
                ),
            },
            "query": {
                "type": "string",
                "description": "搜索查询词（action=search 时必填）。",
            },
            "url": {
                "type": "string",
                "description": "要提取内容的网页 URL（action=extract 时必填）。",
            },
            "provider": {
                "type": "string",
                "enum": ["brave", "tavily", "firecrawl", "jina"],
                "description": "可选，指定服务商；不填则按配置优先级自动选择。",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 10,
                "description": "可选，返回结果数量上限。",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "text"],
                "default": "markdown",
                "description": "可选，extract 输出格式。",
            },
        },
        "required": ["action"],
    },
    side_effect_level=SideEffectLevel.READ_ONLY,
    timeout=60.0,
)


# ─── 执行器 ───────────────────────────────────────────────

_HELP_TEXT = """## web_search 使用指南

### search - 搜索网页
{"action": "search", "query": "搜索内容"}
可选参数: provider(brave|tavily|firecrawl|jina), max_results(默认10)

### extract - 提取网页正文
{"action": "extract", "url": "https://example.com"}
可选参数: provider(tavily|firecrawl|jina), format(markdown|text)

### 说明
- 不指定 provider 时按配置优先级自动选择（默认 brave > tavily > firecrawl > jina）
- 指定服务商失败时会自动回退到下一个可用服务商
- extract 不支持 brave 服务商"""


class WebSearchExecutor:
    """web_search 工具执行器。"""

    def __init__(self, config_service: ConfigService | None = None) -> None:
        self._config_service = config_service

    # ─── 配置 ─────────────────────────────────────────────

    def _search_config(self) -> Any:
        """获取搜索配置（每次执行实时读取，配置修改无需重启）。"""
        svc = self._config_service or ConfigService.get_instance()
        return svc.config.search

    def _build_providers(self) -> list[SearchProvider]:
        """按优先级构建可用服务商列表（只包含已配置 API Key 的）。"""
        cfg = self._search_config()
        pi_keys = _load_pi_search_keys()

        available: dict[str, SearchProvider] = {}
        for name in _PROVIDER_NAMES:
            api_key = _resolve_api_key(name, cfg, pi_keys)
            if not api_key:
                continue
            available[name] = _PROVIDER_CLASSES[name](api_key, cfg.timeout)

        priority = [p.strip() for p in cfg.priority.split(",") if p.strip()]
        ordered = [name for name in priority if name in available]
        # 未出现在 priority 中的已配置服务商追加到末尾
        ordered.extend(n for n in available if n not in ordered)
        return [available[name] for name in ordered]

    # ─── 主入口 ───────────────────────────────────────────

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        cancellation: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        action = (tool_call.arguments.get("action") or "").strip()
        if action == "help":
            return self._ok(tool_call, _HELP_TEXT)
        if action == "search":
            return await self._do_search(tool_call)
        if action == "extract":
            return await self._do_extract(tool_call)
        return self._err(
            tool_call,
            f"未知 action: {action!r}。支持: help / search / extract。"
            "不确定用法时先调用 action=help 查看指南。",
        )

    # ─── search ───────────────────────────────────────────

    async def _do_search(self, tool_call: ToolCall) -> ToolResult:
        query = (tool_call.arguments.get("query") or "").strip()
        if not query:
            return self._err(tool_call, "错误：action=search 需要提供 query 参数。")

        cfg = self._search_config()
        max_results = int(tool_call.arguments.get("max_results") or cfg.max_results)
        max_results = max(1, min(max_results, 20))
        provider_name = (tool_call.arguments.get("provider") or "").strip() or None
        kwargs = {"max_results": max_results}

        providers = self._build_providers()
        if not providers:
            return self._err(
                tool_call,
                "未配置搜索服务商 API Key。请在 设置 → 搜索 中配置至少一个服务商"
                "（Brave/Tavily/Firecrawl/Jina），或设置对应环境变量。",
            )

        last_error: Exception | None = None
        tried: list[str] = []
        try:
            ordered = self._iter_providers(providers, provider_name)
        except _ProviderError as e:
            return self._err(tool_call, str(e))
        for provider in ordered:
            tried.append(provider.name)
            try:
                response = await provider.search(query, **kwargs)
                return self._format_search(tool_call, response)
            except Exception as e:
                log.warning("web_search 服务商 %s 失败: %s", provider.name, e)
                last_error = e

        detail = f"（尝试了: {', '.join(tried)}）" if tried else ""
        return self._err(
            tool_call,
            f"所有可用搜索服务商都失败了{detail}。最后错误: {last_error}",
        )

    def _iter_providers(
        self, providers: list[SearchProvider], provider_name: str | None
    ) -> list[SearchProvider]:
        """确定服务商尝试顺序：指定服务商优先，其余按优先级。"""
        if not provider_name:
            return providers
        specified = next((p for p in providers if p.name == provider_name), None)
        if specified is None:
            available = ", ".join(p.name for p in providers)
            raise _ProviderError(f"服务商 {provider_name!r} 未配置或不可用。可用: {available}")
        return [specified, *(p for p in providers if p.name != provider_name)]

    def _format_search(
        self, tool_call: ToolCall, response: SearchResponse
    ) -> ToolResult:
        lines = [
            f"搜索: {response.query}",
            f"来源: {response.source} | 结果: {len(response.results)} 条"
            f" | 耗时: {response.response_time:.2f}s",
        ]
        if not response.results:
            lines.append("")
            lines.append("未找到相关结果。")
            return self._ok(tool_call, "\n".join(lines))

        for i, item in enumerate(response.results, start=1):
            snippet = item.content.strip() or "(无摘要)"
            if len(snippet) > _SNIPPET_LIMIT:
                snippet = snippet[:_SNIPPET_LIMIT] + "…"
            lines.extend([
                "",
                f"{i}. {item.title or '(无标题)'}",
                f"   {item.url}",
                f"   {snippet}",
            ])
        return self._ok(tool_call, "\n".join(lines))

    # ─── extract ──────────────────────────────────────────

    async def _do_extract(self, tool_call: ToolCall) -> ToolResult:
        url = (tool_call.arguments.get("url") or "").strip()
        if not url:
            return self._err(tool_call, "错误：action=extract 需要提供 url 参数。")
        if not url.startswith(("http://", "https://")):
            return self._err(tool_call, f"错误：url 不是合法的 http(s) 地址: {url}")

        fmt = tool_call.arguments.get("format") or "markdown"
        provider_name = (tool_call.arguments.get("provider") or "").strip() or None
        kwargs = {"format": fmt}

        providers = [
            p for p in self._build_providers()
            if p.name in _EXTRACT_PROVIDERS
        ]
        if not providers:
            return self._err(
                tool_call,
                "未配置支持 extract 的服务商（Tavily/Firecrawl/Jina）。"
                "请在 设置 → 搜索 中配置 API Key。",
            )

        last_error: Exception | None = None
        tried: list[str] = []
        try:
            ordered = self._iter_providers(providers, provider_name)
        except _ProviderError as e:
            return self._err(tool_call, str(e))
        for provider in ordered:
            tried.append(provider.name)
            try:
                result = await provider.extract(url, **kwargs)
                return self._format_extract(tool_call, result)
            except Exception as e:
                log.warning("web_search extract 服务商 %s 失败: %s", provider.name, e)
                last_error = e

        detail = f"（尝试了: {', '.join(tried)}）" if tried else ""
        return self._err(
            tool_call,
            f"所有可用提取服务商都失败了{detail}。最后错误: {last_error}",
        )

    def _format_extract(
        self, tool_call: ToolCall, result: dict[str, Any]
    ) -> ToolResult:
        content = (result.get("content") or "").strip()
        if len(content) > _EXTRACT_LIMIT:
            content = content[:_EXTRACT_LIMIT] + "…"

        lines = [
            f"标题: {result.get('title') or '(无标题)'}",
            f"URL: {result.get('url', '')}",
            f"来源: {result.get('source', '')}",
            "",
            content or "(无内容)",
        ]
        return self._ok(tool_call, "\n".join(lines))

    # ─── 结果封装 ─────────────────────────────────────────

    def _ok(self, tool_call: ToolCall, text: str) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=text)],
        )

    def _err(self, tool_call: ToolCall, text: str) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text=text)],
            is_error=True,
        )


class _ProviderError(Exception):
    """服务商选择错误（如指定了未配置的服务商）。"""
