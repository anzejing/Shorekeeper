"""Run 存储接口。

RunStore 负责 Run 状态的持久化和查询。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.runtime.models import RunId, RunSnapshot, RunStatus


@runtime_checkable
class RunStore(Protocol):
    """Run 存储接口。

    职责：
    1. 创建和更新 Run 状态
    2. 按 ID 查询 Run
    3. 按状态查询活跃 Run（用于崩溃恢复）
    """

    async def save(self, snapshot: RunSnapshot) -> None:
        """保存或更新 Run 快照。

        如果 Run 不存在则创建，存在则更新。
        使用乐观锁：version 必须匹配才能更新。

        Args:
            snapshot: Run 快照。

        Raises:
            VersionConflictError: 版本不匹配。
        """
        ...  # pragma: no cover

    async def get(self, run_id: RunId) -> RunSnapshot | None:
        """按 ID 查询 Run。

        Args:
            run_id: Run ID。

        Returns:
            Run 快照，不存在则返回 None。
        """
        ...  # pragma: no cover

    async def list_active(self) -> list[RunSnapshot]:
        """查询所有活跃 Run（非终态）。

        用于崩溃恢复：扫描 RUNNING/WAITING/RESUMING/CANCELLING 的 Run。

        Returns:
            活跃 Run 快照列表。
        """
        ...  # pragma: no cover
