"""Configuration schema — Pydantic models for each config group."""

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """服务器配置"""

    host: str = Field("0.0.0.0", description="API 服务监听地址")
    port: int = Field(8000, ge=1, le=65535, description="API 服务监听端口")
    workers: int = Field(1, ge=1, description="工作进程数")


class LogConfig(BaseModel):
    """日志配置"""

    level: str = Field(
        "INFO",
        description="日志级别",
        json_schema_extra={"options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    )
    file: str = Field("logs/shorekeeper.log", description="日志文件路径")
    max_size: str = Field("10MB", description="单文件最大大小")
    backup_count: int = Field(5, ge=0, description="备份文件数量")


class StorageConfig(BaseModel):
    """存储配置"""

    database_url: str = Field(
        "sqlite:///shorekeeper.db", description="数据库连接地址（相对于数据目录）"
    )
    backup_enabled: bool = Field(True, description="是否启用自动备份")


class SecurityConfig(BaseModel):
    """安全配置"""

    session_timeout: int = Field(3600, ge=60, description="会话超时（秒）")


class UIConfig(BaseModel):
    """界面配置"""

    theme: str = Field(
        "system",
        description="主题",
        json_schema_extra={"options": ["light", "dark", "system"]},
    )
    language: str = Field(
        "zh-CN",
        description="语言",
        json_schema_extra={"options": ["zh-CN", "en-US"]},
    )


class MCPServerConfig(BaseModel):
    """单个 MCP 服务器配置"""

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
    auto_approve: list[str] = Field(default_factory=list, description="自动批准的工具名列表")


class MCPConfig(BaseModel):
    """MCP 全局配置"""

    servers: list[MCPServerConfig] = Field(default_factory=list, description="MCP 服务器列表")


class SearchConfig(BaseModel):
    """网络搜索（web_search 工具）配置"""

    brave_api_key: str = Field(
        "",
        description="Brave Search API Key",
        json_schema_extra={"secret": True},
    )
    tavily_api_key: str = Field(
        "",
        description="Tavily API Key",
        json_schema_extra={"secret": True},
    )
    firecrawl_api_key: str = Field(
        "",
        description="Firecrawl API Key",
        json_schema_extra={"secret": True},
    )
    jina_api_key: str = Field(
        "",
        description="Jina AI API Key",
        json_schema_extra={"secret": True},
    )
    priority: str = Field(
        "brave,tavily,firecrawl,jina",
        description="服务商优先级（逗号分隔，越靠前越优先）",
    )
    max_results: int = Field(10, ge=1, le=20, description="搜索默认最大结果数")
    timeout: float = Field(30.0, ge=1, le=120, description="请求超时（秒）")


class ProxyConfig(BaseModel):
    """代理配置（外网请求统一走代理，失败可回退直连）"""

    enabled: bool = Field(False, description="全局代理开关（models.dev / web_search 跟随）")
    url: str = Field(
        "",
        description="代理地址（http/https，可含认证，如 http://user:pass@host:port）",
        json_schema_extra={"secret": True},
    )
    fallback_direct: bool = Field(
        True, description="代理失败时自动直连重试（仅连接类错误）"
    )
    timeout: float = Field(
        10.0, ge=1, le=120, description="代理连接超时（秒）"
    )


class AppConfig(BaseModel):
    """应用总配置（模型相关配置已迁移至数据库，见 models_config 模块）"""

    server: ServerConfig = ServerConfig()
    log: LogConfig = LogConfig()
    storage: StorageConfig = StorageConfig()
    security: SecurityConfig = SecurityConfig()
    ui: UIConfig = UIConfig()
    mcp: MCPConfig = MCPConfig()
    search: SearchConfig = SearchConfig()
    proxy: ProxyConfig = ProxyConfig()
