"""统一安装入口：SKILL.md 文件 / zip / tar.gz → 自动判断安装为 Skill 或插件。

- 单 SKILL.md → 独立 Skill（复用 SkillService.install_skill 原逻辑）
- 压缩包含 plugin.json → 插件（安装到 plugins/）
- 压缩包是 Skill 目录（含 SKILL.md）→ 独立 Skill（原逻辑）
- 其他 → InstallError

安全防护：
- zip slip / tar 路径逃逸：条目路径必须留在目标目录内
- zip bomb：限制解压后总大小与条目数
- 符号链接（tar）：拒绝
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from app.plugin.manifest import ManifestError, load_manifest
from app.skill.models import SKILL_FILENAME, SkillListResponse

log = logging.getLogger(__name__)

# ─── 常量 ─────────────────────────────────────────────────

MAX_TOTAL_SIZE = 50 * 1024 * 1024   # 解压后总大小上限 50MB
MAX_ENTRIES = 1000                  # 条目数上限

# 支持的压缩包扩展名
ZIP_EXTENSIONS = {".zip"}
TAR_EXTENSIONS = {".tar.gz", ".tgz", ".tar"}

# SKILL.md 魔数：frontmatter 起始标记
SKILL_MAGIC = "---"


class InstallError(Exception):
    """安装失败（格式不支持 / 结构不识别 / 校验失败 / 安全违规）。"""


class InstallResult:
    """安装结果（可序列化为 InstallResponse）。"""

    def __init__(
        self,
        type_: str,
        skills: list[Any],
        plugin_name: str | None = None,
    ) -> None:
        self.type = type_
        self.skills = skills
        self.plugin_name = plugin_name


# ─── 入口 ─────────────────────────────────────────────────


async def install_bundle(
    file_bytes: bytes,
    filename: str,
    *,
    skill_service: Any,
    skills_dir: Path,
    plugins_dir: Path,
) -> InstallResult:
    """统一安装入口：根据文件类型自动判断安装方式。

    Args:
        file_bytes: 上传文件内容。
        filename: 上传文件名（用于判断类型）。
        skill_service: SkillService 实例。
        skills_dir: 独立 Skill 安装目录。
        plugins_dir: 插件安装目录。

    Returns:
        InstallResult（type: 'skill' | 'plugin'）。

    Raises:
        InstallError: 格式不支持 / 结构不识别 / 校验或安全违规。
    """
    lower = filename.lower()

    # ── 单 SKILL.md ──
    if lower.endswith(".md") or _looks_like_skill_md(file_bytes):
        return await _install_single_skill(file_bytes, skill_service)

    # ── 压缩包 ──
    if any(lower.endswith(ext) for ext in ZIP_EXTENSIONS):
        extracted = _extract_zip(file_bytes, filename)
    elif any(lower.endswith(ext) for ext in TAR_EXTENSIONS):
        extracted = _extract_tar(file_bytes, filename)
    else:
        raise InstallError(
            "不支持的文件格式：请上传 SKILL.md 文件或压缩包（.zip / .tar.gz）"
        )

    try:
        return await _install_extracted(extracted, skill_service, skills_dir, plugins_dir)
    finally:
        # 清理临时解压目录
        shutil.rmtree(extracted, ignore_errors=True)


# ─── 单 SKILL.md ──────────────────────────────────────────


async def _install_single_skill(
    file_bytes: bytes, skill_service: Any
) -> InstallResult:
    """安装单 SKILL.md（原逻辑）。"""
    try:
        content = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise InstallError("SKILL.md 必须是 UTF-8 编码")

    skill = await skill_service.install_skill(skill_md_content=content)
    return InstallResult(type_="skill", skills=[skill])


def _looks_like_skill_md(content: bytes) -> bool:
    """启发式判断：内容是否以 frontmatter 起始标记开头。"""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return text.startswith(SKILL_MAGIC)


# ─── 压缩包解压（安全） ───────────────────────────────────


def _extract_zip(file_bytes: bytes, filename: str) -> Path:
    """解压 zip 到临时目录（含 zip slip / bomb 防护）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        raise InstallError(f"{filename} 不是有效的 zip 压缩包")

    target = _make_temp_dir()
    total_size = 0

    try:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir():
                continue

            # zip slip 防护
            dest = _safe_join(target, name)
            if dest is None:
                raise InstallError(f"压缩包包含非法路径条目: {name}")

            # bomb 防护
            total_size += info.file_size
            if total_size > MAX_TOTAL_SIZE:
                raise InstallError("压缩包解压后超过大小限制（50MB）")
            if len(zf.infolist()) > MAX_ENTRIES:
                raise InstallError("压缩包条目数超过限制")

            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    except InstallError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        zf.close()

    return target


def _extract_tar(file_bytes: bytes, filename: str) -> Path:
    """解压 tar.gz / tar 到临时目录（含路径逃逸 / bomb / 符号链接防护）。"""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(file_bytes), mode="r:*")
    except tarfile.TarError:
        raise InstallError(f"{filename} 不是有效的 tar 压缩包")

    target = _make_temp_dir()
    total_size = 0
    count = 0

    try:
        for member in tf.getmembers():
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise InstallError(f"压缩包包含符号链接，已拒绝: {member.name}")

            count += 1
            if count > MAX_ENTRIES:
                raise InstallError("压缩包条目数超过限制")

            total_size += member.size
            if total_size > MAX_TOTAL_SIZE:
                raise InstallError("压缩包解压后超过大小限制（50MB）")

            # 路径逃逸防护
            dest = _safe_join(target, member.name)
            if dest is None:
                raise InstallError(f"压缩包包含非法路径条目: {member.name}")

            dest.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, open(dest, "wb") as out:
                if src is not None:
                    shutil.copyfileobj(src, out)
    except InstallError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        tf.close()

    return target


def _make_temp_dir() -> Path:
    """创建临时解压目录。"""
    import tempfile

    return Path(tempfile.mkdtemp(prefix="shorekeeper-install-"))


def _safe_join(root: Path, name: str) -> Path | None:
    """将压缩包条目名安全拼接到 root，逃逸则返回 None。"""
    if name.startswith("/") or "\\" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    dest = root.joinpath(*parts)
    try:
        dest.resolve().relative_to(root.resolve())
        return dest
    except ValueError:
        return None


# ─── 结构分类与安装 ───────────────────────────────────────


async def _install_extracted(
    extracted: Path,
    skill_service: Any,
    skills_dir: Path,
    plugins_dir: Path,
) -> InstallResult:
    """分析解压目录结构并安装。"""
    kind = _classify(extracted)

    if kind == "plugin":
        return await _install_plugin(extracted, skill_service, plugins_dir)
    if kind == "skill":
        return await _install_skill_dir(extracted, skill_service, skills_dir)

    raise InstallError("无法识别的压缩包结构")


def _classify(extracted: Path) -> str:
    """分类：'plugin' | 'skill' | 抛 InstallError。"""
    if (extracted / "plugin.json").is_file():
        return "plugin"

    if (extracted / SKILL_FILENAME).is_file():
        return "skill"

    # 单子目录打包的 Skill（如 xxx/SKILL.md）
    subs = [d for d in extracted.iterdir() if d.is_dir()]
    if len(subs) == 1 and (subs[0] / SKILL_FILENAME).is_file():
        return "skill"

    raise InstallError(
        "无法识别的压缩包结构：需要包含 plugin.json（插件）或 SKILL.md（Skill 目录）"
    )


async def _install_plugin(
    extracted: Path,
    skill_service: Any,
    plugins_dir: Path,
) -> InstallResult:
    """安装插件：校验 manifest → 复制到 plugins/{name}/ → 刷新 → 返回其 skills。"""
    # 校验 manifest
    try:
        manifest = load_manifest(extracted / "plugin.json")
    except ManifestError as e:
        raise InstallError(f"插件清单校验失败: {e}")

    target = plugins_dir / manifest.name
    if target.exists():
        raise InstallError(f"插件 {manifest.name} 已存在，请先卸载再安装")

    # 复制插件目录（排除解压残留）
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(extracted, target)

    # 刷新缓存，加载新插件
    await skill_service.reload()

    # 收集该插件的 skills
    plugin_skills = [
        s for s in (await skill_service.list_skills()).skills
        if s.plugin_name == manifest.name
    ]
    if not plugin_skills:
        # 插件无有效 skill，仍算安装成功（§6.2 缺失不算错误）
        log.warning("插件 %s 安装成功但无有效 Skill", manifest.name)

    return InstallResult(
        type_="plugin",
        skills=plugin_skills,
        plugin_name=manifest.name,
    )


async def _install_skill_dir(
    extracted: Path,
    skill_service: Any,
    skills_dir: Path,
) -> InstallResult:
    """安装 Skill 目录打包：复用 install_skill（SKILL.md + attachments）。"""
    # 定位 SKILL.md 所在目录（根或单子目录）
    skill_root = extracted
    if not (skill_root / SKILL_FILENAME).is_file():
        subs = [d for d in extracted.iterdir() if d.is_dir()]
        skill_root = subs[0]

    skill_md_content = (skill_root / SKILL_FILENAME).read_text(encoding="utf-8")

    # 目录内所有其他文件作为附带文件
    attachments: dict[str, bytes] = {}
    for f in skill_root.rglob("*"):
        if f.is_file() and f.name != SKILL_FILENAME:
            rel = f.relative_to(skill_root)
            attachments[str(rel)] = f.read_bytes()

    skill = await skill_service.install_skill(
        skill_md_content=skill_md_content,
        attachments=attachments,
    )
    return InstallResult(type_="skill", skills=[skill])
