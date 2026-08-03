"""Skill 模块数据模型。

两层模型：
- SkillInfo: 从 SKILL.md 文件解析的内容（只读）
- SkillState: 数据库中的运行时状态（可写）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ─── SKILL.md Frontmatter 字段 ───────────────────────────

# SKILL.md 格式（兼容 skills.sh / Claude Code 规范）：
#
# ---
# name: deploy
# description: 部署应用到生产环境
# category: utility
# version: 1.0.0
# author: shorekeeper
# ---
#
# # Deploy Skill
#
# 系统提示词内容...


# ─── 从文件解析的 Skill 信息 ──────────────────────────────


@dataclass
class SkillInfo:
    """从 SKILL.md 解析出的 Skill 信息（只读）。

    这些内容来自文件系统，不存数据库。
    """

    name: str                    # 唯一标识，来自 frontmatter
    description: str             # 简短描述，来自 frontmatter
    category: str                # memory | utility | custom
    version: str                 # 版本号
    author: str                  # 作者
    system_prompt: str           # SKILL.md body，注入到系统消息
    path: Path                   # SKILL.md 文件路径
    has_scripts: bool = False    # 目录中是否有脚本文件（.sh, .py 等）


# ─── 数据库存储的 Skill 状态 ──────────────────────────────


@dataclass
class SkillState:
    """Skill 的运行时状态（数据库）。

    只存储用户可修改的状态，不存储文件内容。
    """

    name: str                    # 关联 SkillInfo.name
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    installed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Pydantic 模型（API 请求/响应）─────────────────────────


class SkillResponse(BaseModel):
    """Skill 完整响应（合并 SkillInfo + SkillState）。"""

    name: str
    description: str
    category: str
    version: str = ""
    author: str = ""
    enabled: bool
    system_prompt: str
    path: str                  # 文件路径（字符串）
    has_scripts: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    installed_at: datetime | None = None


class SkillListResponse(BaseModel):
    """Skill 列表响应。"""

    skills: list[SkillResponse]
    total: int


class UpdateSkillRequest(BaseModel):
    """更新 Skill 请求。"""

    enabled: bool | None = None
    config: dict[str, Any] | None = None


# ─── SKILL.md 解析结果 ────────────────────────────────────


# SKILL.md frontmatter 必填字段
REQUIRED_FIELDS = {"name", "description"}

# SKILL.md frontmatter 可选字段及默认值
OPTIONAL_FIELDS = {
    "category": "custom",
    "version": "0.0.0",
    "author": "unknown",
}

# 脚本文件扩展名
SCRIPT_EXTENSIONS = {".sh", ".py", ".js", ".ts", ".rb", ".pl"}

# SKILL.md 文件名
SKILL_FILENAME = "SKILL.md"
