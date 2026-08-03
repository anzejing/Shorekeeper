"""Configuration schema — Pydantic models for each config group."""

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """服务器配置"""

    host: str = Field("0.0.0.0", description="API 服务监听地址")
    port: int = Field(8000, ge=1, le=65535, description="API 服务监听端口")
    workers: int = Field(1, ge=1, description="工作进程数")


class RuntimeConfig(BaseModel):
    """AI Runtime 配置"""

    base_url: str = Field(
        "",
        description="API Base URL（OpenAI 兼容格式，留空使用默认）",
    )
    api_key: str = Field(
        "",
        description="AI Runtime API Key",
        json_schema_extra={"secret": True},
    )
    model: str = Field("gpt-4", description="默认模型")
    temperature: float = Field(0.7, ge=0, le=2, description="温度参数")
    max_tokens: int = Field(4096, ge=1, description="最大 Token 数")


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


class AppConfig(BaseModel):
    """应用总配置"""

    server: ServerConfig = ServerConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    log: LogConfig = LogConfig()
    storage: StorageConfig = StorageConfig()
    security: SecurityConfig = SecurityConfig()
    ui: UIConfig = UIConfig()
