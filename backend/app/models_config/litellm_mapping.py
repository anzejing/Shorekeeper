"""kind → litellm 前缀映射。

将 provider 类型映射为 litellm 模型名前缀，生成发给 litellm 的完整模型名。
"""

from __future__ import annotations

from app.models_config.schema import PROVIDER_KINDS

# provider kind → litellm 前缀
# 注意：openai 官方与 openai 兼容端点（openai_like）在 litellm 中均使用
# openai/ 前缀，区别在于 openai_like 必须配置 api_base（litellm 1.94.1
# 的 openai_like/ 前缀不可用，实测 Unmapped provider）。
_KIND_PREFIX: dict[str, str] = {
    "openai": "openai",
    "openai_like": "openai",  # 兼容端点：openai/ + api_base
    "anthropic": "anthropic",
    "gemini": "gemini",
}

# models.dev npm 包名 → provider kind（未知的保守归为 openai_like）
_NPM_KIND_MAP: dict[str, str] = {
    "@ai-sdk/openai": "openai",
    "@ai-sdk/openai-compatible": "openai_like",
    "@ai-sdk/anthropic": "anthropic",
    "@ai-sdk/google": "gemini",
    "@ai-sdk/xai": "openai_like",
    "@ai-sdk/mistral": "openai_like",
    "@openrouter/ai-sdk-provider": "openai_like",
}


def build_litellm_name(kind: str, model_id: str) -> str:
    """生成 litellm 完整模型名，如 openai_like/deepseek-v4-flash。"""
    prefix = _KIND_PREFIX.get(kind)
    if not prefix:
        raise ValueError(f"不支持的 provider 类型: {kind}")
    return f"{prefix}/{model_id}"


def kind_from_npm(npm: str | None) -> str:
    """根据 models.dev 的 npm 字段推断 provider kind。"""
    if not npm:
        return "openai_like"
    return _NPM_KIND_MAP.get(npm, "openai_like")


def default_base_url(kind: str) -> str:
    """官方端点 base_url（留空表示使用 litellm 内置默认）。"""
    return {
        "openai": "",
        "openai_like": "",
        "anthropic": "",
        "gemini": "",
    }.get(kind, "")


# kind → 官方端点 URL（catalog default_base_url 预填用；兼容类型无官方端点）
_OFFICIAL_BASE_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openai_like": "",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}


def official_base_url(kind: str) -> str:
    """kind 对应的官方端点 URL（向导预填 Base URL 用）；未知/兼容类型返回空。"""
    return _OFFICIAL_BASE_URL.get(kind, "")


def normalize_anthropic_base_url(base_url: str) -> str:
    """归一化 anthropic base_url 供 litellm 使用。

    litellm 会自动追加 /v1/messages（main.py）；而 models.dev 的 api 字段
    （AI SDK 语义）常以 /v1 结尾，直接传入会变成 .../v1/v1/messages 404。

    - 以 /v1/messages 结尾 → 原样（已是完整端点）
    - 以 /v1 结尾 → 去掉 /v1（litellm 会拼回 /v1/messages）
    - 其他 → 原样（litellm 拼 /v1/messages）
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return base_url
    if base.endswith("/v1/messages"):
        return base
    if base.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def validate_kind(kind: str) -> None:
    """校验 provider kind 合法性。"""
    if kind not in PROVIDER_KINDS:
        raise ValueError(
            f"不支持的 provider 类型: {kind}（可选: {', '.join(PROVIDER_KINDS)}）"
        )
