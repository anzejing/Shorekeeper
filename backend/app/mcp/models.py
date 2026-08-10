"""MCP 模块数据模型。

MCP 服务器配置和状态定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── 传输类型 ─────────────────────────────────────────────


class MCPTransport(str, Enum):
    """MCP 服务器传输类型。"""

    STDIO = "stdio"              # 子进程 stdio
    STREAMABLE_HTTP = "streamable_http"  # HTTP SSE


class MCPServerStatus(str, Enum):
    """MCP 服务器连接状态。"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ─── 配置模型（Pydantic，持久化到 YAML/DB）────────────────


class MCPServerConfig(BaseModel):
    """单个 MCP 服务器的配置。"""

    name: str = Field(description="服务器唯一标识")
    transport: MCPTransport = Field(default=MCPTransport.STDIO, description="传输类型")
    enabled: bool = Field(default=True, description="是否启用")

    # stdio 配置
    command: str = Field(default="", description="stdio 启动命令（如 npx, uvx）")
    args: list[str] = Field(default_factory=list, description="命令参数")
    env: dict[str, str] | None = Field(default=None, description="环境变量")
    cwd: str | None = Field(default=None, description="工作目录")

    # streamable-http 配置
    url: str = Field(default="", description="HTTP 服务地址")
    headers: dict[str, str] | None = Field(default=None, description="HTTP 请求头")

    # 通用配置
    timeout: float = Field(default=30.0, description="连接超时（秒）")
    auto_approve: list[str] = Field(
        default_factory=list,
        description="自动批准的工具名列表（跳过审批）",
    )


class MCPConfig(BaseModel):
    """MCP 全局配置。"""

    servers: list[MCPServerConfig] = Field(default_factory=list)


# ─── 运行时状态（dataclass，不持久化）─────────────────────


@dataclass
class MCPServerState:
    """MCP 服务器运行时状态。"""

    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    tools: list[dict[str, Any]] = field(default_factory=list)  # 发现的工具列表
    error: str | None = None          # 最近一次错误
    session: Any = None               # MCP ClientSession（运行时持有）
    read_stream: Any = None           # 底层读流
    write_stream: Any = None          # 底层写流
