"""BashParser — Shell 命令解析器。

使用 shlex 进行词法分析，解析 shell 命令为 ParsedAction AST。
支持复合命令、重定向、管道、子命令提取。

不做手写字符串切分，使用结构化解析。
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from app.permission.models import (
    AnalysisCompleteness,
    ParsedAction,
    Redirection,
    new_action_id,
)
from app.runtime.models import ToolCall


# ─── Shell 操作符 ─────────────────────────────────────────

OPERATORS = {";", "&&", "||", "|"}

# 重定向模式
REDIRECT_PATTERN = re.compile(
    r"^(\d*)(&?>&?|<?&?|<<<?|>>?)\s*(.*)$"
)

# 动态执行标记
DYNAMIC_EXECUTABLES = {"eval", "source", "."}

# 包含子命令的模式
SUBCOMMAND_PATTERNS = {
    "bash": ["-c"],
    "sh": ["-c"],
    "find": ["-exec", "-ok"],
    "xargs": [],  # xargs 的参数本身就是子命令
}


class BashParser:
    """Shell 命令解析器。

    解析流程：
    1. shlex 词法分析（处理引号、转义）
    2. 按操作符拆分为 segments
    3. 每个 segment 解析为 ParsedAction
    4. 检测子命令（find -exec, bash -c, xargs）
    5. 递归解析子命令
    """

    def parse(self, tool_call: ToolCall) -> ParsedAction:
        command = tool_call.arguments.get("command", "")
        if not command:
            return self._make_empty(command)
        return self._parse_command(command, operator_before=None)

    def _parse_command(self, command: str, operator_before: str | None) -> ParsedAction:
        """解析单条或复合命令。"""
        # 1. 按操作符拆分
        segments = self._split_operators(command)

        if len(segments) > 1:
            children = []
            for seg in segments:
                child = self._parse_command(seg["command"], seg["operator"])
                children.append(child)
            return ParsedAction(
                action_id=new_action_id(),
                executable=None,
                args=[],
                flags={},
                redirections=[],
                operator_before=operator_before,
                children=children,
                raw=command,
                parse_completeness=self._worst_completeness(children),
                parse_warnings=self._merge_warnings(children),
            )

        # 2. 单一命令 → 词法分析
        return self._parse_single_command(command, operator_before)

    def _parse_single_command(self, command: str, operator_before: str | None) -> ParsedAction:
        """解析单一命令（无操作符）。"""
        # shlex 词法分析
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            # 无法解析（引号未闭合等）
            return ParsedAction(
                action_id=new_action_id(),
                executable=None,
                args=[],
                flags={},
                redirections=[],
                operator_before=operator_before,
                children=[],
                raw=command,
                parse_completeness=AnalysisCompleteness.UNKNOWN,
                parse_warnings=[f"shlex 解析失败: {e}"],
            )

        if not tokens:
            return self._make_empty(command)

        # 3. 提取重定向
        tokens, redirections = self._extract_redirections(tokens)

        # 4. 提取 executable, args, flags
        executable = tokens[0] if tokens else None
        args, flags = self._parse_args(tokens[1:])

        # 5. 检测动态执行
        completeness = AnalysisCompleteness.COMPLETE
        warnings: list[str] = []
        if self._is_dynamic(executable, args):
            completeness = AnalysisCompleteness.UNKNOWN
            warnings.append(f"动态执行: {executable}")

        # 6. 提取子命令
        children = self._extract_children(executable, args, flags)
        if children:
            child_comp = self._worst_completeness(children)
            if child_comp == AnalysisCompleteness.UNKNOWN:
                completeness = AnalysisCompleteness.UNKNOWN
            elif child_comp == AnalysisCompleteness.PARTIAL and completeness != AnalysisCompleteness.UNKNOWN:
                completeness = AnalysisCompleteness.PARTIAL
            warnings.extend(self._merge_warnings(children))

        return ParsedAction(
            action_id=new_action_id(),
            executable=executable,
            args=args,
            flags=flags,
            redirections=redirections,
            operator_before=operator_before,
            children=children,
            raw=command,
            parse_completeness=completeness,
            warnings=warnings,
        )

    def _split_operators(self, command: str) -> list[dict[str, str | None]]:
        """按 shell 操作符拆分命令。

        返回 [{"command": "...", "operator": ";"|"&&"|"||"|"|"}, ...]
        """
        segments: list[dict[str, str | None]] = []
        current = ""
        i = 0
        chars = command

        while i < len(chars):
            c = chars[i]

            # 跳过引号内的内容
            if c in ("'", '"'):
                quote = c
                current += c
                i += 1
                while i < len(chars) and chars[i] != quote:
                    current += chars[i]
                    i += 1
                if i < len(chars):
                    current += chars[i]
                    i += 1
                continue

            # 检测操作符
            if c == ';' and (i == 0 or chars[i-1] != '\\'):
                if current.strip():
                    segments.append({"command": current.strip(), "operator": None})
                segments.append({"command": "", "operator": ";"})
                current = ""
                i += 1
                continue

            if i + 1 < len(chars):
                two = chars[i:i+2]
                if two in ("&&", "||"):
                    if current.strip():
                        segments.append({"command": current.strip(), "operator": None})
                    segments.append({"command": "", "operator": two})
                    current = ""
                    i += 2
                    continue

            if c == '|' and (i == 0 or chars[i-1] != '\\'):
                if current.strip():
                    segments.append({"command": current.strip(), "operator": None})
                segments.append({"command": "", "operator": "|"})
                current = ""
                i += 1
                continue

            current += c
            i += 1

        if current.strip():
            segments.append({"command": current.strip(), "operator": None})

        # 合并操作符到前一个 segment
        merged: list[dict[str, str | None]] = []
        for seg in segments:
            if seg["command"] == "" and seg["operator"]:
                # 操作符，附加到下一个 segment
                if merged:
                    merged[-1] = {**merged[-1], "_next_op": seg["operator"]}
            else:
                merged.append(seg)

        # 重新组织为 command + operator
        result: list[dict[str, str | None]] = []
        for seg in merged:
            result.append({
                "command": seg["command"],
                "operator": seg.get("_next_op"),
            })

        return result if result else [{"command": command, "operator": None}]

    def _extract_redirections(self, tokens: list[str]) -> tuple[list[str], list[Redirection]]:
        """从 token 列表中提取重定向。"""
        clean_tokens: list[str] = []
        redirections: list[Redirection] = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # 检测重定向模式
            m = REDIRECT_PATTERN.match(token)
            if m:
                fd_str, op, target = m.groups()
                fd = int(fd_str) if fd_str else None

                # 目标可能在下一个 token（如 > file）
                if not target and i + 1 < len(tokens):
                    i += 1
                    target = tokens[i]

                if target:
                    redirections.append(Redirection(fd=fd, operator=op, target=target))
                    i += 1
                    continue

            # 检测 >> 和 > 等独立 token
            if token in (">>", ">", "<", ">&", "<&", "<<", "<<<"):
                if i + 1 < len(tokens):
                    redirections.append(Redirection(fd=None, operator=token, target=tokens[i+1]))
                    i += 2
                    continue

            clean_tokens.append(token)
            i += 1

        return clean_tokens, redirections

    def _parse_args(self, tokens: list[str]) -> tuple[list[str], dict[str, Any]]:
        """解析参数和选项。"""
        args: list[str] = []
        flags: dict[str, Any] = {}

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("--"):
                # 长选项
                if "=" in token:
                    key, value = token[2:].split("=", 1)
                    flags[key] = value
                elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    flags[token[2:]] = tokens[i + 1]
                    i += 1
                else:
                    flags[token[2:]] = True
            elif token.startswith("-") and len(token) > 1:
                # 短选项
                flag_char = token[1:]
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    flags[flag_char] = tokens[i + 1]
                    i += 1
                else:
                    flags[flag_char] = True
            else:
                args.append(token)

            i += 1

        return args, flags

    def _is_dynamic(self, executable: str | None, args: list[str]) -> bool:
        """检测是否为动态执行。"""
        if executable in DYNAMIC_EXECUTABLES:
            return True
        # 检测 $(), ``, eval 等
        for arg in args:
            if "$(" in arg or "`" in arg or "eval" in arg:
                return True
        return False

    def _extract_children(
        self, executable: str | None, args: list[str], flags: dict[str, Any]
    ) -> list[ParsedAction]:
        """提取隐式子命令（find -exec, xargs, bash -c 等）。"""
        children: list[ParsedAction] = []

        if executable in ("bash", "sh") and "-c" in args:
            idx = args.index("-c")
            if idx + 1 < len(args):
                children.append(self._parse_command(args[idx + 1], operator_before=None))
                return children

        if executable == "find":
            # find -exec cmd {} \;
            for key, value in flags.items():
                if key in ("exec", "ok") and isinstance(value, str):
                    # 清理 {} 和 \;
                    cmd = value.replace("{}", "").replace("\\;", "").strip()
                    if cmd:
                        child = self._parse_command(cmd, operator_before=None)
                        children.append(
                            ParsedAction(
                                action_id=child.action_id,
                                executable=child.executable,
                                args=child.args,
                                flags=child.flags,
                                redirections=child.redirections,
                                operator_before=child.operator_before,
                                children=child.children,
                                raw=child.raw,
                                parse_completeness=AnalysisCompleteness.PARTIAL,
                                parse_warnings=child.parse_warnings + [
                                    "find -exec 子命令的参数在运行时展开"
                                ],
                            )
                        )

        if executable == "xargs" and args:
            children.append(self._parse_command(" ".join(args), operator_before=None))

        return children

    def _worst_completeness(self, actions: list[ParsedAction]) -> AnalysisCompleteness:
        """取所有子动作中最差的完整度。"""
        order = {
            AnalysisCompleteness.COMPLETE: 0,
            AnalysisCompleteness.PARTIAL: 1,
            AnalysisCompleteness.UNKNOWN: 2,
        }
        worst = AnalysisCompleteness.COMPLETE
        for a in actions:
            if order[a.parse_completeness] > order[worst]:
                worst = a.parse_completeness
        return worst

    def _merge_warnings(self, actions: list[ParsedAction]) -> list[str]:
        """合并所有子动作的警告。"""
        warnings: list[str] = []
        for a in actions:
            warnings.extend(a.parse_warnings)
        return warnings

    def _make_empty(self, raw: str) -> ParsedAction:
        return ParsedAction(
            action_id=new_action_id(),
            executable=None,
            args=[],
            flags={},
            redirections=[],
            operator_before=None,
            children=[],
            raw=raw,
            parse_completeness=AnalysisCompleteness.COMPLETE,
            parse_warnings=[],
        )
