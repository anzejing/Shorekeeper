"""Configuration API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app.config.meta import build_config_items
from app.config.service import ConfigService

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    value: Any


class ConfigUpdateResponse(BaseModel):
    key: str
    value: Any
    reload_required: bool = False


class ConfigResetResponse(BaseModel):
    message: str


@router.get("")
async def get_config():
    """Get all configuration items (secrets masked)."""
    svc = ConfigService.get_instance()
    return build_config_items(svc.config)


@router.put("/{key:path}", response_model=ConfigUpdateResponse)
async def update_config(key: str, body: ConfigUpdateRequest):
    """Update a single config value."""
    svc = ConfigService.get_instance()

    # Determine if this key needs restart
    restart_keys = {"server.port", "server.host", "server.workers", "storage.database_url"}
    reload_required = key in restart_keys

    try:
        svc.set(key, body.value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Read back the value (may be masked)
    try:
        new_value = svc.get(key)
    except KeyError:
        new_value = body.value

    return ConfigUpdateResponse(
        key=key,
        value=new_value,
        reload_required=reload_required,
    )


@router.post("/reset", response_model=ConfigResetResponse)
async def reset_config():
    """Reset all configuration to defaults."""
    svc = ConfigService.get_instance()
    svc.reset()
    return ConfigResetResponse(message="配置已重置为默认值")
