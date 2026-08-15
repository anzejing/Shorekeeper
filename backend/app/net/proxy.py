"""代理工具模块。

提供统一的代理配置读取与连接类错误判定：
- get_proxy_url: 全局代理开关开启时返回代理地址
- is_conn_error: 判断异常是否为连接类错误（连接失败/超时/TLS/代理不可达），
  用于"代理失败 → 直连回退"的判定依据。
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

# 代理配置键
_ENABLED = "enabled"
_URL = "url"
_FALLBACK = "fallback_direct"
_TIMEOUT = "timeout"


def _proxy_cfg(config: Any) -> Any:
    """从 ConfigService（或 AppConfig）取出 ProxyConfig；无配置返回 None。"""
    app = getattr(config, "config", config)
    if app is None:
        return None
    return getattr(app, "proxy", None)


def proxy_enabled(config: Any) -> bool:
    """全局代理开关是否开启。"""
    p = _proxy_cfg(config)
    return bool(p and getattr(p, _ENABLED, False))


def get_proxy_url(config: Any) -> str | None:
    """代理地址：全局开关开启且 url 非空时返回，否则 None。"""
    if not proxy_enabled(config):
        return None
    p = _proxy_cfg(config)
    url = (getattr(p, _URL, "") or "").strip()
    return url or None


def fallback_direct_enabled(config: Any) -> bool:
    """代理失败是否回退直连。"""
    p = _proxy_cfg(config)
    return bool(p and getattr(p, _FALLBACK, True))


def get_proxy_timeout(config: Any) -> float:
    """代理连接超时（秒）。"""
    p = _proxy_cfg(config)
    return float(getattr(p, _TIMEOUT, 10.0)) if p else 10.0


def build_proxy_client(
    proxy_url: str,
    api_key: str | None,
    api_base: str | None,
) -> AsyncOpenAI:
    """构造带代理的 AsyncOpenAI 客户端（httpx proxy），用于 litellm 调用。"""
    http_client = httpx.AsyncClient(
        proxy=proxy_url,
        trust_env=False,
        timeout=httpx.Timeout(60.0),
    )
    return AsyncOpenAI(
        api_key=api_key or "",
        base_url=api_base or None,
        http_client=http_client,
    )


async def close_proxy_client(client: AsyncOpenAI) -> None:
    """关闭代理客户端（含底层 httpx 连接池）。"""
    try:
        await client.close()
    except Exception:
        log.debug("关闭代理客户端失败", exc_info=True)


# 供异步生成器串联 chunk 流使用
async def chain_first(first: Any, rest: AsyncIterator[Any]) -> AsyncIterator[Any]:
    """将首个元素与后续流串联为单一迭代。"""
    yield first
    async for item in rest:
        yield item


def is_conn_error(error: Exception) -> bool:
    """判断异常是否为连接类错误（适合回退直连）。

    True: 连接失败/拒绝/DNS 失败/超时/TLS 错误/代理不可达/服务端断开。
    False: HTTP 业务错误（4xx/5xx）、认证错误等（直连重试无意义）。
    """
    # asyncio 超时（连接/读取阶段）
    if isinstance(error, asyncio.TimeoutError):
        return True

    # aiohttp 连接层错误
    try:
        import aiohttp

        if isinstance(
            error,
            (
                aiohttp.ClientConnectorError,
                aiohttp.ClientProxyConnectionError,
                aiohttp.ClientOSError,
                aiohttp.ClientSSLError,
                aiohttp.ServerDisconnectedError,
                aiohttp.ServerConnectionError,
                aiohttp.ClientConnectionError,
            ),
        ):
            return True
    except ImportError:
        pass

    # httpx 连接层错误
    try:
        import httpx

        if isinstance(
            error,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.NetworkError,
                httpx.ProxyError,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
    except ImportError:
        pass

    # 底层 socket / DNS 错误（aiohttp/httpx 常包装为 ClientConnectorError/ConnectError，
    # 但某些场景直接暴露 socket 错误）
    import socket

    if isinstance(error, (socket.gaierror, socket.timeout, ConnectionError, OSError)):
        # OSError 需排除普通业务 IO 错误？连接层 OSError（ECONNREFUSED 等）属于连接失败
        return True

    if isinstance(error, ssl.SSLError):
        return True

    # openai SDK / litellm 包装错误
    try:
        import openai

        if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
            return True
    except ImportError:
        pass

    try:
        import litellm.exceptions as litellm_ex

        if isinstance(error, (litellm_ex.APIConnectionError, litellm_ex.Timeout)):
            return True
    except ImportError:
        pass

    # litellm 等可能将连接错误包装为通用异常（如 InternalServerError），
    # 递归检查 cause / provider_error 链
    inner = getattr(error, "provider_error", None)
    if inner is None:
        inner = error.__cause__
    if inner is not None and inner is not error:
        if is_conn_error(inner):
            return True

    # 字符串兜底：litellm 包装后消息含 Connection error
    msg = str(error).lower()
    if "connection error" in msg or "connection failed" in msg:
        return True

    return False
