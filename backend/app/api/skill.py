"""Skill HTTP API。

提供 Skill 管理、统一安装（SKILL.md / zip / tar.gz 自动判断）、插件删除的 REST 接口。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.plugin.installer import InstallError, install_bundle
from app.skill.models import (
    InstallResponse,
    SkillListResponse,
    SkillResponse,
    UpdateSkillRequest,
)
from app.skill.service import SkillService

router = APIRouter(prefix="/api/skills", tags=["skills"])

# SkillService 实例由 main.py 注入
_service: SkillService | None = None


def init_skill_api(service: SkillService) -> None:
    """初始化 Skill API，注入 SkillService。"""
    global _service
    _service = service


def _get_service() -> SkillService:
    """获取 SkillService 实例。"""
    if _service is None:
        raise HTTPException(status_code=503, detail="Skill 模块未初始化")
    return _service


# ─── Skill 管理 ──────────────────────────────────────────


@router.get("", response_model=SkillListResponse)
async def list_skills(
    enabled: bool | None = None,
) -> SkillListResponse:
    """列出 Skill。"""
    service = _get_service()
    return await service.list_skills(enabled=enabled)


@router.get("/{name}", response_model=SkillResponse)
async def get_skill(name: str) -> SkillResponse:
    """获取 Skill 详情。"""
    service = _get_service()
    result = await service.get_skill(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")
    return result


@router.patch("/{name}", response_model=SkillResponse)
async def update_skill(
    name: str,
    request: UpdateSkillRequest,
) -> SkillResponse:
    """更新 Skill 状态（启用/禁用、配置）。"""
    service = _get_service()
    try:
        return await service.update_skill(
            name=name,
            enabled=request.enabled,
            config=request.config,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")


# ─── 安装/卸载 ───────────────────────────────────────────


@router.post("/install", response_model=InstallResponse, status_code=201)
async def install_skill(
    file: UploadFile = File(description="SKILL.md 文件或压缩包（.zip / .tar.gz）"),
    target_name: str | None = Form(default=None, description="目标目录名（仅单 SKILL.md 生效）"),
) -> InstallResponse:
    """统一安装入口：自动判断 SKILL.md / zip / tar.gz。"""
    service = _get_service()

    content = await file.read()
    filename = file.filename or "skill.md"

    try:
        # 兼容旧调用：单 SKILL.md + 指定目录名
        if target_name and content.lstrip().startswith(b"---"):
            skill = await service.install_skill(
                skill_md_content=content.decode("utf-8"),
                target_name=target_name,
            )
            return InstallResponse(type="skill", skills=[skill])

        result = await install_bundle(
            content,
            filename,
            skill_service=service,
            skills_dir=service.skills_dir,
            plugins_dir=service.plugins_dir,
        )
    except (UnicodeDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InstallError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return InstallResponse(
        type=result.type,
        skills=result.skills,
        plugin_name=result.plugin_name,
    )


@router.delete("/{name}", status_code=204)
async def uninstall_skill(name: str) -> None:
    """卸载 Skill（删除文件和数据库记录）。"""
    service = _get_service()
    deleted = await service.uninstall_skill(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {name}")


# ─── 刷新 ────────────────────────────────────────────────


@router.post("/reload", response_model=SkillListResponse)
async def reload_skills() -> SkillListResponse:
    """重新扫描 skills 目录与插件目录（手动安装 Skill 后调用）。"""
    service = _get_service()
    await service.reload()
    return await service.list_skills()


# ─── 插件管理 ─────────────────────────────────────────────


@router.delete("/plugins/{plugin_name}", status_code=204)
async def uninstall_plugin(plugin_name: str) -> None:
    """卸载插件（删除插件目录及其所有 Skill 记录）。"""
    service = _get_service()
    deleted = await service.uninstall_plugin(plugin_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"插件不存在: {plugin_name}")
