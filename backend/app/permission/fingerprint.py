"""ToolCall Fingerprint — 生成与校验。

fingerprint 用于审批绑定，确保审批后的执行参数与审批时一致。
包含 capability metadata，防止参数变更绕过审批。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.permission.models import (
    ExecutionClaim,
    ResolvedCapability,
    ToolCallFingerprint,
)


def compute_fingerprint(
    tool_name: str,
    canonical_arguments: dict[str, Any],
    capabilities: list[ResolvedCapability],
    workspace_id: str,
    run_id: str,
    session_id: str,
) -> str:
    """生成 ToolCall 的规范化指纹。

    包含：
    - tool_name
    - 规范化的 arguments
    - 每个 capability 的 capability + metadata
    - workspace_id, run_id, session_id
    """
    cap_data = []
    for c in sorted(capabilities, key=lambda x: x.capability):
        cap_data.append({
            "capability": c.capability,
            "metadata": _canonicalize(c.metadata),
        })

    canonical = {
        "tool_name": tool_name,
        "arguments": _canonicalize(canonical_arguments),
        "capabilities": cap_data,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "session_id": session_id,
    }

    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_fingerprint(
    claim: ExecutionClaim,
    tool_name: str,
    canonical_arguments: dict[str, Any],
    capabilities: list[ResolvedCapability],
    workspace_id: str,
    run_id: str,
    session_id: str,
) -> bool:
    """校验执行声明的 fingerprint 是否与当前 ToolCall 一致。"""
    expected = compute_fingerprint(
        tool_name, canonical_arguments, capabilities,
        workspace_id, run_id, session_id,
    )
    return claim.tool_call_fingerprint == expected


def _canonicalize(obj: Any) -> Any:
    """规范化数据结构用于 fingerprint 计算。"""
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 10)
    return obj
