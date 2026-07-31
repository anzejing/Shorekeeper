"""Runtime 状态机。

管理 Run 的生命周期状态转换。
定义合法转换，拒绝非法转换，支持乐观锁版本检查。

合法转换：
    CREATED → QUEUED
    QUEUED → RUNNING
    RUNNING → WAITING, COMPLETED, FAILED, CANCELLING, TERMINATED
    WAITING → RESUMING, CANCELLING, TERMINATED
    RESUMING → RUNNING, FAILED
    CANCELLING → CANCELLED, FAILED

终态（不可转换）：COMPLETED, CANCELLED, TERMINATED, FAILED
"""

from __future__ import annotations

from app.runtime.models import RunStatus

# ─── 合法转换表 ────────────────────────────────────────────

_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.QUEUED},
    RunStatus.QUEUED: {RunStatus.RUNNING},
    RunStatus.RUNNING: {
        RunStatus.WAITING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLING,
        RunStatus.TERMINATED,
    },
    RunStatus.WAITING: {
        RunStatus.RESUMING,
        RunStatus.CANCELLING,
        RunStatus.TERMINATED,
    },
    RunStatus.RESUMING: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.CANCELLING: {RunStatus.CANCELLED, RunStatus.FAILED},
    # 终态：无合法转换
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.TERMINATED: set(),
}


# ─── 异常 ─────────────────────────────────────────────────


class InvalidTransitionError(Exception):
    """非法状态转换。"""

    def __init__(self, current: RunStatus, target: RunStatus) -> None:
        super().__init__(f"非法转换: {current.value} → {target.value}")
        self.current = current
        self.target = target


class VersionConflictError(Exception):
    """乐观锁版本冲突。"""

    def __init__(self, run_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"版本冲突: run={run_id}, expected={expected}, actual={actual}"
        )
        self.run_id = run_id
        self.expected = expected
        self.actual = actual


# ─── 状态机 ───────────────────────────────────────────────


class RunStateMachine:
    """Run 状态机。

    管理单个 Run 的状态转换，支持乐观锁版本检查。
    实例绑定到一个 Run 的生命周期，不跨 Run 复用。

    用法：
        sm = RunStateMachine(run_id, RunStatus.CREATED, version=0)
        new_status = sm.transition(RunStatus.QUEUED)
        new_status = sm.transition(RunStatus.RUNNING)
    """

    def __init__(self, run_id: str, status: RunStatus, version: int = 0) -> None:
        self._run_id = run_id
        self._status = status
        self._version = version

    @property
    def status(self) -> RunStatus:
        """当前状态。"""
        return self._status

    @property
    def version(self) -> int:
        """当前版本号。"""
        return self._version

    @property
    def is_terminal(self) -> bool:
        """是否处于终态。"""
        return self._status in {
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.TERMINATED,
            RunStatus.FAILED,
        }

    @property
    def is_active(self) -> bool:
        """是否处于活跃状态（可继续执行）。"""
        return self._status in {
            RunStatus.CREATED,
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING,
            RunStatus.RESUMING,
            RunStatus.CANCELLING,
        }

    def can_transition(self, target: RunStatus) -> bool:
        """检查是否可以转换到目标状态。"""
        allowed = _TRANSITIONS.get(self._status, set())
        return target in allowed

    def get_allowed_transitions(self) -> set[RunStatus]:
        """获取当前状态允许的所有目标状态。"""
        return set(_TRANSITIONS.get(self._status, set()))

    def transition(self, target: RunStatus, expected_version: int | None = None) -> RunStatus:
        """执行状态转换。

        Args:
            target: 目标状态。
            expected_version: 乐观锁版本号。如果不为 None，必须匹配当前版本。

        Returns:
            转换后的新状态。

        Raises:
            InvalidTransitionError: 非法转换。
            VersionConflictError: 版本不匹配。
        """
        # 版本检查
        if expected_version is not None and expected_version != self._version:
            raise VersionConflictError(self._run_id, expected_version, self._version)

        # 转换检查
        allowed = _TRANSITIONS.get(self._status, set())
        if target not in allowed:
            raise InvalidTransitionError(self._status, target)

        # 执行转换
        self._status = target
        self._version += 1
        return self._status

    def recover(self, status: RunStatus) -> None:
        """崩溃恢复时直接设置状态，不做转换检查。

        仅用于启动时扫描恢复，不递增版本号。
        """
        self._status = status


# ─── 崩溃恢复辅助 ──────────────────────────────────────────


def get_recovery_action(status: RunStatus) -> str:
    """获取崩溃恢复时应执行的动作。

    Returns:
        "resume": 从最近 checkpoint 恢复执行
        "wait": 保持不变，等待 resume
        "continue_cancel": 继续取消流程
        "none": 终态，无需处理
    """
    if status in {RunStatus.RUNNING, RunStatus.RESUMING}:
        return "resume"
    if status == RunStatus.WAITING:
        return "wait"
    if status == RunStatus.CANCELLING:
        return "continue_cancel"
    return "none"
