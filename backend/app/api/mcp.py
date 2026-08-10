"""MCP HTTP API — MCP 服务器管理。

提供 MCP 服务器的查询、添加、删除、重连等接口。
操作会持久化到 config.yaml。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.mcp.models import MCPServerConfig, MCPTransport

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_service = None
_config_service = None


def init_mcp_api(service, config_service=None) -> None:
    """注入 MCPService 和 ConfigService。"""
    global _service, _config_service
    _service = service
    _config_service = config_service


def _get_service():
    if _service is None:
        raise HTTPException(status_code=503, detail="MCP 模块未初始化")
    return _service


def _persist_mcp_config() -> None:
    """将当前 MCP 服务器配置持久化到 config.yaml。"""
    if _config_service is None or _service is None:
        return

    # 从 MCPService 的运行时状态构建配置
    servers_data: list[dict[str, Any]] = []
    for state in _service.list_servers():
        cfg = state.config
        servers_data.append({
            "name": cfg.name,
            "transport": cfg.transport.value,
            "enabled": cfg.enabled,
            "command": cfg.command,
            "args": cfg.args,
            "env": cfg.env,
            "cwd": cfg.cwd,
            "url": cfg.url,
            "headers": cfg.headers,
            "timeout": cfg.timeout,
            "auto_approve": cfg.auto_approve,
        })

    try:
        _config_service.set("mcp.servers", servers_data)
        log.info("MCP 配置已持久化: %d 个服务器", len(servers_data))
    except Exception:
        log.exception("MCP 配置持久化失败")


# ─── 请求/响应模型 ────────────────────────────────────────


class MCPServerResponse(BaseModel):
    """MCP 服务器状态响应。"""

    name: str
    transport: str
    enabled: bool
    status: str
    tools_count: int = 0
    error: str | None = None
    command: str = ""
    url: str = ""


class MCPListResponse(BaseModel):
    """MCP 服务器列表响应。"""

    servers: list[MCPServerResponse]
    total: int


class AddMCPServerRequest(BaseModel):
    """添加 MCP 服务器请求。"""

    name: str = Field(description="服务器唯一标识")
    transport: str = Field("stdio", description="传输类型: stdio / streamable_http")
    enabled: bool = Field(True, description="是否启用")
    command: str = Field("", description="stdio 启动命令")
    args: list[str] = Field(default_factory=list, description="命令参数")
    env: dict[str, str] | None = Field(None, description="环境变量")
    cwd: str | None = Field(None, description="工作目录")
    url: str = Field("", description="HTTP 服务地址")
    headers: dict[str, str] | None = Field(None, description="HTTP 请求头")
    timeout: float = Field(30.0, description="连接超时（秒）")


# ─── API 端点 ─────────────────────────────────────────────


@router.get("", response_model=MCPListResponse)
async def list_servers() -> MCPListResponse:
    """列出所有 MCP 服务器。"""
    service = _get_service()
    states = service.list_servers()

    servers = []
    for state in states:
        servers.append(MCPServerResponse(
            name=state.config.name,
            transport=state.config.transport.value,
            enabled=state.config.enabled,
            status=state.status.value,
            tools_count=len(state.tools),
            error=state.error,
            command=state.config.command,
            url=state.config.url,
        ))

    return MCPListResponse(servers=servers, total=len(servers))


@router.post("", response_model=MCPServerResponse)
async def add_server(request: AddMCPServerRequest) -> MCPServerResponse:
    """添加并连接一个 MCP 服务器。操作持久化到 config.yaml。"""
    service = _get_service()

    existing = service.get_server_state(request.name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"服务器 '{request.name}' 已存在")

    try:
        transport = MCPTransport(request.transport)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的传输类型: {request.transport}，可选: stdio / streamable_http",
        )

    config = MCPServerConfig(
        name=request.name,
        transport=transport,
        enabled=request.enabled,
        command=request.command,
        args=request.args,
        env=request.env,
        cwd=request.cwd,
        url=request.url,
        headers=request.headers,
        timeout=request.timeout,
    )

    try:
        await service.add_server(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"连接失败: {e}")

    # 持久化
    _persist_mcp_config()

    state = service.get_server_state(request.name)
    return MCPServerResponse(
        name=state.config.name,
        transport=state.config.transport.value,
        enabled=state.config.enabled,
        status=state.status.value,
        tools_count=len(state.tools),
        error=state.error,
        command=state.config.command,
        url=state.config.url,
    )


@router.delete("/{name}")
async def remove_server(name: str) -> dict:
    """移除 MCP 服务器。操作持久化到 config.yaml。"""
    service = _get_service()
    try:
        await service.remove_server(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 持久化
    _persist_mcp_config()

    return {"ok": True, "name": name}


@router.post("/{name}/reconnect", response_model=MCPServerResponse)
async def reconnect_server(name: str) -> MCPServerResponse:
    """重连 MCP 服务器。"""
    service = _get_service()
    try:
        await service.reconnect_server(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重连失败: {e}")

    state = service.get_server_state(name)
    return MCPServerResponse(
        name=state.config.name,
        transport=state.config.transport.value,
        enabled=state.config.enabled,
        status=state.status.value,
        tools_count=len(state.tools),
        error=state.error,
        command=state.config.command,
        url=state.config.url,
    )
