"""模型配置数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 支持的 provider 类型（对应 litellm 前缀）
PROVIDER_KINDS = ("openai", "openai_like", "anthropic", "gemini")

# 元数据来源
META_SOURCES = ("models_dev", "provider_api", "custom")


class ModelProvider(BaseModel):
    """已配置的 LLM Provider。"""

    provider_id: str = Field(description="唯一标识（小写连字符）")
    name: str = Field(description="显示名称")
    kind: str = Field(
        description="provider 类型: openai / openai_like / anthropic / gemini"
    )
    base_url: str = Field(
        "", description="API Base URL（openai_like 必填，其余留空用官方端点）"
    )
    api_key: str = Field("", description="API Key（secret，响应中掩码）")
    enabled: bool = Field(True, description="是否启用")
    source: str = Field(
        "custom", description="来源: catalog（models.dev 导入）/ custom（自建）"
    )
    created_at: str = Field("", description="创建时间（ISO）")
    updated_at: str = Field("", description="更新时间（ISO）")


class ModelEntry(BaseModel):
    """provider 下的一个模型。"""

    provider_id: str = Field(description="所属 provider id")
    model_id: str = Field(description="模型 id（如 deepseek-v4-flash）")
    display_name: str = Field(description="显示名称")
    litellm_name: str = Field(
        description="发给 litellm 的完整名（含前缀，如 openai_like/deepseek-v4-flash）"
    )
    enabled: bool = Field(True, description="是否启用")
    meta_source: str = Field(
        "custom", description="元数据来源: models_dev / provider_api / custom"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="models.dev 元数据（cost/context/tool_call 等，供计量使用）",
    )


class CatalogMeta(BaseModel):
    """models.dev 目录同步元信息。"""

    etag: str = Field("", description="上次同步的 ETag")
    data_date: str = Field("", description="数据版本日期（模型 last_updated 最大值）")
    synced_at: str = Field("", description="上次同步时间（ISO）")
    provider_count: int = Field(0, description="目录 provider 数")
    model_count: int = Field(0, description="目录模型数")


class CurrentModel(BaseModel):
    """全局当前模型。"""

    provider_id: str = Field(description="provider id")
    model_id: str = Field(description="模型 id")
    litellm_name: str = Field(description="litellm 完整名")
    display_name: str = Field(description="显示名")
