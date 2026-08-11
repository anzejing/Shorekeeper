"""pytest 全局配置。

aiosqlite 连接会创建非守护 worker 线程；若测试结束后连接未关闭，
Python 解释器退出时会永久等待（threading._shutdown 卡死）。

这里通过自动 fixture 追踪本会话内创建的所有 aiosqlite 连接，
并在会话结束时统一关闭，释放 worker 线程。
"""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

# 本会话内创建的所有 aiosqlite 连接
_TRACKED_CONNECTIONS: list[aiosqlite.Connection] = []


@pytest.fixture(autouse=True)
def _track_aiosqlite_connections(monkeypatch):
    """追踪每个测试中创建的 aiosqlite 连接。"""
    original_connect = aiosqlite.connect

    async def tracking_connect(*args, **kwargs):
        conn = await original_connect(*args, **kwargs)
        _TRACKED_CONNECTIONS.append(conn)
        return conn

    monkeypatch.setattr(aiosqlite, "connect", tracking_connect)
    yield


@pytest.fixture(scope="session", autouse=True)
def _close_aiosqlite_connections_at_session_end():
    """会话结束时关闭所有连接，释放 worker 线程。"""
    yield

    if not _TRACKED_CONNECTIONS:
        return

    async def _close_all() -> None:
        for conn in _TRACKED_CONNECTIONS:
            try:
                await conn.close()
            except Exception:
                pass

    try:
        asyncio.run(_close_all())
    except Exception:
        pass
