"""Checkpoint 存储接口。

CheckpointStore 负责在 Agent Loop 的 step 边界持久化状态快照。
用于崩溃恢复和 suspend/resume 场景。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.runtime.models import Checkpoint, RunId


@runtime_checkable
class CheckpointStore(Protocol):
    """Checkpoint 存储接口。

    职责：
    1. 在 step 边界保存 Checkpoint（包含 RunSnapshot + PendingWrites）
    2. 加载最新 Checkpoint 用于恢复
    3. 支持按 RunId 查询
    """

    async def save(self, checkpoint: Checkpoint) -> None:
        """保存一个 checkpoint。

        Args:
            checkpoint: 要保存的检查点。
        """
        ...  # pragma: no cover

    async def load_latest(self, run_id: RunId) -> Checkpoint | None:
        """加载指定 Run 的最新 checkpoint。

        Args:
            run_id: Run ID。

        Returns:
            最新的 Checkpoint，如果没有则返回 None。
        """
        ...  # pragma: no cover
