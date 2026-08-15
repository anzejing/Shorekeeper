"""模型管理 API 端点。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models_config.service import ModelConfigService

router = APIRouter(prefix="/api/models", tags=["models"])

# 依赖由 main.py 注入
_service: ModelConfigService | None = None

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def init_models_api(service: ModelConfigService) -> None:
    """初始化模型管理 API。"""
    global _service
    _service = service


def _get_service() -> ModelConfigService:
    if _service is None:
        raise HTTPException(status_code=503, detail="模型配置模块未初始化")
    return _service


def _validate_provider_id(provider_id: str) -> str:
    if not _PROVIDER_ID_RE.match(provider_id):
        raise HTTPException(
            status_code=422,
            detail="provider_id 仅允许小写字母、数字与连字符",
        )
    return provider_id


# ─── 请求/响应模型 ────────────────────────────────────────


class ProviderRequest(BaseModel):
    provider_id: str = Field(description="唯一标识（小写连字符）")
    name: str = ""
    kind: str = Field(description="openai / openai_like / anthropic / gemini")
    base_url: str = ""
    api_key: str = ""
    enabled: bool = True
    use_proxy: bool = False
    source: str = "custom"
    import_models: bool = False


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    use_proxy: bool | None = None
    source: str | None = None


class ModelAddRequest(BaseModel):
    model_id: str = Field(description="模型 id，如 deepseek-v4-flash")


class CurrentModelRequest(BaseModel):
    provider_id: str
    model_id: str


# ─── Provider ─────────────────────────────────────────────


@router.get("/providers")
async def list_providers():
    """已配置 provider 列表（api_key 掩码）。"""
    return await _get_service().list_providers()


@router.post("/providers", status_code=201)
async def create_provider(body: ProviderRequest):
    """新增 provider。"""
    try:
        provider = await _get_service().create_provider(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return provider


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdateRequest):
    """更新 provider。"""
    _validate_provider_id(provider_id)
    try:
        provider = await _get_service().update_provider(
            provider_id, body.model_dump(exclude_none=True)
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return provider


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除 provider（级联删模型；命中当前模型则清空）。"""
    _validate_provider_id(provider_id)
    try:
        await _get_service().delete_provider(provider_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"message": "provider 已删除"}


# ─── 模型 ─────────────────────────────────────────────────


@router.get("/providers/{provider_id}/models")
async def list_models(provider_id: str):
    """provider 下模型列表（含合并元数据）。"""
    _validate_provider_id(provider_id)
    try:
        return await _get_service().list_models(provider_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/providers/{provider_id}/models", status_code=201)
async def add_model(provider_id: str, body: ModelAddRequest):
    """手动添加模型（自动回填 models.dev 元数据）。"""
    _validate_provider_id(provider_id)
    try:
        entry = await _get_service().add_model(provider_id, body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return entry


@router.delete("/providers/{provider_id}/models/{model_id}")
async def remove_model(provider_id: str, model_id: str):
    """删除模型。"""
    _validate_provider_id(provider_id)
    try:
        await _get_service().remove_model(provider_id, model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"message": "模型已删除"}


@router.post("/providers/{provider_id}/sync")
async def sync_provider_models(provider_id: str):
    """调 /models 端点同步模型列表（覆盖合并）。"""
    _validate_provider_id(provider_id)
    try:
        return await _get_service().sync_provider_models(provider_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class TestRequest(BaseModel):
    model_id: str = Field(description="要测试的模型 id")


@router.post("/providers/{provider_id}/test")
async def test_connection(provider_id: str, body: TestRequest):
    """测试连接：向指定模型发最小请求。"""
    _validate_provider_id(provider_id)
    try:
        return await _get_service().test_connection(provider_id, body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ─── models.dev 目录 ──────────────────────────────────────


@router.get("/catalog/status")
async def catalog_status():
    """目录状态（数据日期/etag/计数）。"""
    return await _get_service().catalog_status()


@router.post("/catalog/sync")
async def sync_catalog():
    """手动同步 models.dev 目录（ETag 增量）。"""
    try:
        return await _get_service().sync_catalog()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"目录同步失败: {e}") from e


@router.get("/catalog/providers")
async def catalog_providers(
    search: str = Query("", description="按 id/name 过滤"),
):
    """目录 provider 摘要列表。"""
    return _get_service().catalog_providers(search)


@router.get("/catalog/providers/{provider_id}/models")
async def catalog_provider_models(provider_id: str):
    """目录单 provider 的模型元数据。"""
    data = _get_service().catalog_provider_models(provider_id)
    if data is None:
        raise HTTPException(status_code=404, detail="目录无缓存或 provider 不存在")
    return data


# ─── 全局当前模型 ─────────────────────────────────────────


@router.get("/current")
async def get_current():
    """全局当前模型（可为 null）。"""
    return await _get_service().get_current()


@router.put("/current")
async def set_current(body: CurrentModelRequest):
    """设置全局当前模型。"""
    _validate_provider_id(body.provider_id)
    try:
        return await _get_service().set_current(body.provider_id, body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/current")
async def clear_current():
    """清空全局当前模型。"""
    await _get_service().clear_current()
    return {"message": "当前模型已清空"}
