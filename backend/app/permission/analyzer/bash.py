"""BashAnalyzer — Shell 命令能力分析器。

根据 ParsedAction 识别操作能力和风险元数据。
重点分析：filesystem.delete、network、git 操作、提权等。

支持复合命令：递归分析所有 children，聚合结果。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any

from app.permission.models import (
    AnalysisCompleteness,
    CapabilityAnalysis,
    ParsedAction,
    PROTECTED_PATHS,
    Redirection,
    ResolvedCapability,
    TEMP_DIRS,
)
from app.runtime.models import ToolCall


class BashAnalyzer:
    """Shell 命令能力分析器。"""

    def __init__(self, workspace_dir: str | None = None) -> None:
        self._workspace = Path(workspace_dir) if workspace_dir else Path.cwd()

    def analyze(self, parsed: ParsedAction, tool_call: ToolCall) -> CapabilityAnalysis:
        """分析 ParsedAction，支持复合命令。"""
        if parsed.children:
            return self._analyze_compound(parsed)
        return self._analyze_single(parsed)

    def _analyze_compound(self, parsed: ParsedAction) -> CapabilityAnalysis:
        """分析复合命令——递归分析所有 children。"""
        all_caps: list[ResolvedCapability] = []
        all_warnings: list[str] = list(parsed.parse_warnings)
        worst_completeness = AnalysisCompleteness.COMPLETE

        for child in parsed.children:
            child_analysis = self._analyze_single(child)
            all_caps.extend(child_analysis.capabilities)
            all_warnings.extend(child_analysis.warnings)
            if _completeness_rank(child_analysis.completeness) > _completeness_rank(worst_completeness):
                worst_completeness = child_analysis.completeness

        return CapabilityAnalysis(
            capabilities=all_caps,
            completeness=worst_completeness,
            warnings=all_warnings,
        )

    def _analyze_single(self, parsed: ParsedAction) -> CapabilityAnalysis:
        """分析单一命令。"""
        exe = parsed.executable
        warnings: list[str] = list(parsed.parse_warnings)

        # 动态执行
        if parsed.parse_completeness == AnalysisCompleteness.UNKNOWN:
            return CapabilityAnalysis(
                capabilities=[self._make_cap(
                    "system.execute_dynamic",
                    {"raw": parsed.raw, "executable": exe},
                    parsed.action_id,
                    AnalysisCompleteness.UNKNOWN,
                    warnings,
                )],
                completeness=AnalysisCompleteness.UNKNOWN,
                warnings=warnings,
            )

        # 按 executable 分类
        if exe in ("rm", "unlink", "rmdir"):
            return self._analyze_delete(parsed, warnings)
        elif exe in ("mv", "cp", "install"):
            return self._analyze_move_copy(parsed, warnings)
        elif exe in ("cat", "less", "head", "tail", "grep", "wc", "sort", "uniq", "diff"):
            return self._analyze_read(parsed, warnings)
        elif exe in ("ls", "stat", "file", "du", "df"):
            return self._analyze_list(parsed, warnings)
        elif exe in ("echo", "printf", "tee", "sed", "awk", "tr", "cut"):
            return self._analyze_write(parsed, warnings)
        elif exe in ("mkdir", "touch", "ln"):
            return self._analyze_create(parsed, warnings)
        elif exe in ("chmod", "chown", "chgrp"):
            return self._analyze_permission_change(parsed, warnings)
        elif exe in ("sudo", "su", "doas"):
            return CapabilityAnalysis(
                capabilities=[self._make_cap(
                    "system.elevate",
                    {"command": parsed.raw},
                    parsed.action_id,
                    AnalysisCompleteness.COMPLETE,
                    ["提权操作"],
                )],
                completeness=AnalysisCompleteness.COMPLETE,
                warnings=["提权操作"],
            )
        elif exe in ("git",):
            return self._analyze_git(parsed, warnings)
        elif exe in ("curl", "wget", "http"):
            return self._analyze_network(parsed, warnings)
        elif exe in ("docker", "podman"):
            return self._analyze_container(parsed, warnings)
        elif exe in ("python", "python3", "node", "ruby", "perl", "php"):
            return self._analyze_interpreter(parsed, warnings)
        elif exe in ("find",):
            return self._analyze_find(parsed, warnings)
        elif exe in ("xargs",):
            return self._analyze_xargs(parsed, warnings)
        else:
            # 未知命令
            return CapabilityAnalysis(
                capabilities=[self._make_cap(
                    "system.execute_unknown",
                    {"executable": exe, "raw": parsed.raw},
                    parsed.action_id,
                    parsed.parse_completeness,
                    warnings + [f"未知命令: {exe}"],
                )],
                completeness=parsed.parse_completeness,
                warnings=warnings + [f"未知命令: {exe}"],
            )

    # ─── 文件系统操作 ─────────────────────────────────────

    def _analyze_delete(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        targets = [a for a in parsed.args if a.startswith("-") is False]
        # 过滤掉选项
        targets = [t for t in targets if not t.startswith("-")]

        raw = parsed.raw
        recursive = "-r" in raw or "-rf" in raw or "-R" in raw
        force = "-f" in raw or "-rf" in raw

        metadata: dict[str, Any] = {
            "targets": targets,
            "recursive": recursive,
            "force": force,
            "target_count": len(targets),
            "workspace_relation": self._workspace_relation(targets),
            "protected_path": any(self._is_protected(t) for t in targets),
            "tracked_by_git": None,  # 需要 git 信息时填充
        }

        # 检查重定向（> 也是写入）
        if parsed.redirections:
            for r in parsed.redirections:
                if r.operator in (">", ">>") and self._is_protected(r.target):
                    metadata["protected_path"] = True
                    warnings.append(f"重定向到保护路径: {r.target}")

        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.delete",
                metadata,
                parsed.action_id,
                AnalysisCompleteness.COMPLETE,
                warnings,
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_read(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        targets = [a for a in parsed.args if not a.startswith("-")]
        outside = any(self._is_outside_workspace(t) for t in targets)
        protected = any(self._is_protected(t) for t in targets)

        metadata: dict[str, Any] = {
            "targets": targets,
            "outside_workspace": outside,
            "protected_path": protected,
        }

        capability = "filesystem.read"
        if protected:
            warnings.append(f"读取保护路径: {[t for t in targets if self._is_protected(t)]}")

        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                capability, metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_list(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        targets = [a for a in parsed.args if not a.startswith("-")]
        metadata: dict[str, Any] = {"targets": targets}
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.list", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_write(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        # 检查重定向目标
        targets = []
        for r in parsed.redirections:
            if r.operator in (">", ">>"):
                targets.append(r.target)

        protected = any(self._is_protected(t) for t in targets)
        metadata: dict[str, Any] = {
            "targets": targets,
            "protected_path": protected,
            "append_mode": any(r.operator == ">>" for r in parsed.redirections),
        }

        if protected:
            warnings.append(f"写入保护路径: {[t for t in targets if self._is_protected(t)]}")

        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.write", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_create(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        targets = [a for a in parsed.args if not a.startswith("-")]
        metadata: dict[str, Any] = {"targets": targets}
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.write", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_move_copy(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        args = [a for a in parsed.args if not a.startswith("-")]
        metadata: dict[str, Any] = {
            "sources": args[:-1] if len(args) > 1 else args,
            "destination": args[-1] if len(args) > 1 else None,
        }
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.write", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_permission_change(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        targets = [a for a in parsed.args if not a.startswith("-")]
        metadata: dict[str, Any] = {
            "targets": targets,
            "mode": parsed.args[0] if parsed.args else None,
        }
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "system.config", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    # ─── Git 操作 ─────────────────────────────────────────

    def _analyze_git(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        subcommand = parsed.args[0] if parsed.args else None
        caps: list[ResolvedCapability] = []

        if subcommand in ("push", "remote"):
            if "--force" in parsed.raw or "-f" in parsed.args:
                caps.append(self._make_cap(
                    "repository.force_push",
                    {"subcommand": subcommand, "raw": parsed.raw},
                    parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
                ))
            else:
                caps.append(self._make_cap(
                    "repository.push",
                    {"subcommand": subcommand, "args": parsed.args[1:]},
                    parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
                ))
        elif subcommand in ("merge", "rebase"):
            caps.append(self._make_cap(
                "repository.merge",
                {"subcommand": subcommand},
                parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
            ))
        elif subcommand == "clone":
            caps.append(self._make_cap(
                "network.download",
                {"url": parsed.args[1] if len(parsed.args) > 1 else None},
                parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
            ))
        else:
            caps.append(self._make_cap(
                "repository.read",
                {"subcommand": subcommand},
                parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
            ))

        return CapabilityAnalysis(
            capabilities=caps,
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    # ─── 网络操作 ─────────────────────────────────────────

    def _analyze_network(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        raw = parsed.raw
        is_upload = "-d" in raw or "--data" in raw or "-F" in raw or "--form" in raw
        method = "POST"
        if "-X" in parsed.args:
            idx = parsed.args.index("-X")
            if idx + 1 < len(parsed.args):
                method = parsed.args[idx + 1]

        urls = [a for a in parsed.args if a.startswith("http")]
        metadata: dict[str, Any] = {
            "urls": urls,
            "method": method,
            "is_upload": is_upload,
        }

        capability = "network.upload" if is_upload else "network.request"
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                capability, metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    # ─── 容器操作 ─────────────────────────────────────────

    def _analyze_container(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        subcommand = parsed.args[0] if parsed.args else None
        metadata: dict[str, Any] = {"subcommand": subcommand, "args": parsed.args[1:]}
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "system.process", metadata, parsed.action_id, AnalysisCompleteness.COMPLETE, warnings
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    # ─── 解释器 ───────────────────────────────────────────

    def _analyze_interpreter(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        # python -c "..." → 动态执行
        if "-c" in parsed.args:
            return CapabilityAnalysis(
                capabilities=[self._make_cap(
                    "system.execute_dynamic",
                    {"interpreter": parsed.executable, "raw": parsed.raw},
                    parsed.action_id, AnalysisCompleteness.UNKNOWN,
                    warnings + [f"{parsed.executable} -c 动态执行"],
                )],
                completeness=AnalysisCompleteness.UNKNOWN,
                warnings=warnings + [f"{parsed.executable} -c 动态执行"],
            )
        # 运行脚本文件
        targets = [a for a in parsed.args if not a.startswith("-")]
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "filesystem.execute",
                {"interpreter": parsed.executable, "script": targets},
                parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
            )],
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    # ─── find / xargs ─────────────────────────────────────

    def _analyze_find(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        # find 本身是 list 操作，但 -exec 子命令有独立分析
        caps: list[ResolvedCapability] = [
            self._make_cap(
                "filesystem.list",
                {"path": parsed.args[0] if parsed.args else "."},
                parsed.action_id, AnalysisCompleteness.COMPLETE, warnings,
            )
        ]
        # children 已由 _analyze_compound 处理
        return CapabilityAnalysis(
            capabilities=caps,
            completeness=AnalysisCompleteness.COMPLETE,
            warnings=warnings,
        )

    def _analyze_xargs(self, parsed: ParsedAction, warnings: list[str]) -> CapabilityAnalysis:
        # xargs 的子命令由 _extract_children 处理
        return CapabilityAnalysis(
            capabilities=[self._make_cap(
                "system.execute_unknown",
                {"raw": parsed.raw},
                parsed.action_id, AnalysisCompleteness.PARTIAL,
                warnings + ["xargs 子命令在运行时展开"],
            )],
            completeness=AnalysisCompleteness.PARTIAL,
            warnings=warnings + ["xargs 子命令在运行时展开"],
        )

    # ─── 辅助 ─────────────────────────────────────────────

    def _make_cap(
        self,
        capability: str,
        metadata: dict[str, Any],
        action_id: str,
        completeness: AnalysisCompleteness,
        warnings: list[str],
    ) -> ResolvedCapability:
        return ResolvedCapability(
            capability=capability,
            metadata=metadata,
            source_action_id=action_id,
            completeness=completeness,
            warnings=warnings,
        )

    def _workspace_relation(self, targets: list[str]) -> str:
        """判断目标路径与工作区的关系。"""
        if not targets:
            return "unknown"
        relations = set()
        for t in targets:
            if self._is_outside_workspace(t):
                relations.add("outside")
            elif self._is_workspace_root(t):
                relations.add("root")
            else:
                relations.add("inside")
        if len(relations) > 1:
            return "mixed"
        return relations.pop() if relations else "unknown"

    def _is_outside_workspace(self, target: str) -> bool:
        try:
            p = Path(target).resolve()
            return not str(p).startswith(str(self._workspace.resolve()))
        except (ValueError, OSError):
            return True

    def _is_workspace_root(self, target: str) -> bool:
        try:
            return Path(target).resolve() == self._workspace.resolve()
        except (ValueError, OSError):
            return False

    def _is_protected(self, target: str) -> bool:
        pure = PurePosixPath(target)
        parts = set(pure.parts)
        if parts & PROTECTED_PATHS:
            return True
        # 检查 ~ 展开
        if target.startswith("~/"):
            home_part = target.split("/")[1]
            if home_part in {".ssh", ".gnupg", ".aws", ".env"}:
                return True
        return False


def _completeness_rank(c: AnalysisCompleteness) -> int:
    return {
        AnalysisCompleteness.COMPLETE: 0,
        AnalysisCompleteness.PARTIAL: 1,
        AnalysisCompleteness.UNKNOWN: 2,
    }[c]
