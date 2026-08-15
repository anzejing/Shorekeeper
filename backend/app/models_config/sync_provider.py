"""provider /models 端点同步与连接测试。

- openai / openai_like: GET {base_url}/models（Bearer 认证）
- anthropic: GET {base_url}/v1/models（x-api-key + anthropic-version）
- gemini: GET https://generativelanguage.googleapis.com/v1beta/models（?key=）

三种格式统一转换为 [{id, display_name?}]。
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from app.models_config.schema import ModelProvider
from app.net.proxy import is_conn_error

log = logging.getLogger(__name__)

# 官方端点兜底
_ANTHROPIC_BASE = "https://api.anthropic.com"
_GEMINI_BASE = "https://generativelanguage.googleapis.com"


class ProviderSyncError(Exception):
    """provider /models 端点同步失败。"""


async def fetch_provider_models(
    provider: ModelProvider,
    *,
    timeout: float = 30.0,
    proxy_url: str | None = None,
    fallback_direct: bool = True,
) -> list[dict[str, str]]:
    """调用 provider /models 端点，返回统一模型列表。

    Args:
        provider: provider 配置。
        timeout: 请求超时。
        proxy_url: 代理地址；非空时先走代理（由调用方按 provider.use_proxy 决定）。
        fallback_direct: 代理连接失败时是否回退直连重试一次。

    Returns:
        [{"id": "deepseek-v4-flash", "display_name": "..."}]
    """
    kind = provider.kind
    if kind in ("openai", "openai_like"):
        base = provider.base_url
        if not base:
            if kind == "openai":
                base = "https://api.openai.com/v1"
            else:
                raise ProviderSyncError("openai_like 类型必须配置 base_url")
        url = f"{base.rstrip('/')}/models"
        headers: dict[str, str] = {}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        data = await _get_json(url, headers, timeout, proxy_url, fallback_direct)
        return _parse_openai_models(data)

    if kind == "anthropic":
        base = provider.base_url or _ANTHROPIC_BASE
        url = f"{base.rstrip('/')}/v1/models"
        headers = {
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        }
        data = await _get_json(url, headers, timeout, proxy_url, fallback_direct)
        return _parse_anthropic_models(data)

    if kind == "gemini":
        base = provider.base_url or _GEMINI_BASE
        url = f"{base.rstrip('/')}/v1beta/models"
        if provider.api_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={provider.api_key}"
        data = await _get_json(url, {}, timeout, proxy_url, fallback_direct)
        return _parse_gemini_models(data)

    raise ProviderSyncError(f"不支持的 provider 类型: {kind}")


async def _get_json(
    url: str,
    headers: dict[str, str],
    timeout: float,
    proxy_url: str | None = None,
    fallback_direct: bool = True,
) -> dict[str, Any]:
    """GET 请求并解析 JSON，失败抛 ProviderSyncError。

    代理连接失败时可按 fallback_direct 回退直连重试一次。
    """
    try:
        return await _get_json_once(url, headers, timeout, proxy_url)
    except ProviderSyncError:
        raise
    except Exception as e:
        if proxy_url and fallback_direct and is_conn_error(e):
            log.warning("/models 代理失败，回退直连: %s", e)
            return await _get_json_once(url, headers, timeout, None)
        raise ProviderSyncError(f"/models 请求失败: {e}") from e


async def _get_json_once(
    url: str,
    headers: dict[str, str],
    timeout: float,
    proxy: str | None,
) -> dict[str, Any]:
    """单次 GET 请求并解析 JSON。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    raise ProviderSyncError(
                        f"/models 请求失败: HTTP {resp.status} - {body}"
                    )
                return await resp.json()
    except ProviderSyncError:
        raise
    except Exception as e:
        raise ProviderSyncError(f"/models 请求失败: {e}") from e


def _parse_openai_models(data: dict[str, Any]) -> list[dict[str, str]]:
    """解析 OpenAI 兼容格式 {object, data: [{id, owned_by}]}。"""
    items = data.get("data") or []
    result: list[dict[str, str]] = []
    for item in items:
        mid = item.get("id")
        if mid:
            result.append({"id": str(mid), "display_name": str(mid)})
    return result


def _parse_anthropic_models(data: dict[str, Any]) -> list[dict[str, str]]:
    """解析 Anthropic 格式 {data: [{id, display_name, type}]}。"""
    items = data.get("data") or []
    result: list[dict[str, str]] = []
    for item in items:
        mid = item.get("id")
        if mid and item.get("type") == "model":
            result.append(
                {
                    "id": str(mid),
                    "display_name": item.get("display_name") or str(mid),
                }
            )
    return result


def _parse_gemini_models(data: dict[str, Any]) -> list[dict[str, str]]:
    """解析 Gemini 格式 {models: [{name: "models/xxx", displayName}]}。"""
    items = data.get("models") or []
    result: list[dict[str, str]] = []
    for item in items:
        name = item.get("name") or ""
        # name 形如 "models/gemini-2.5-pro"
        mid = name.split("/")[-1] if "/" in name else name
        if mid:
            result.append(
                {
                    "id": mid,
                    "display_name": item.get("displayName") or mid,
                }
            )
    return result
