"""Runtime 状态机测试。"""

from __future__ import annotations

import pytest

from app.runtime.models import RunStatus
from app.runtime.state import (
    InvalidTransitionError,
    RunStateMachine,
    VersionConflictError,
    get_recovery_action,
)


# ─── 合法转换测试 ──────────────────────────────────────────


class TestLegalTransitions:
    def test_created_to_queued(self) -> None:
        sm = RunStateMachine("r1", RunStatus.CREATED)
        assert sm.transition(RunStatus.QUEUED) == RunStatus.QUEUED

    def test_queued_to_running(self) -> None:
        sm = RunStateMachine("r1", RunStatus.QUEUED)
        assert sm.transition(RunStatus.RUNNING) == RunStatus.RUNNING

    @pytest.mark.parametrize(
        "target",
        [
            RunStatus.WAITING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.TERMINATED,
        ],
    )
    def test_running_to(self, target: RunStatus) -> None:
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        assert sm.transition(target) == target

    @pytest.mark.parametrize(
        "target",
        [RunStatus.RESUMING, RunStatus.CANCELLING, RunStatus.TERMINATED],
    )
    def test_waiting_to(self, target: RunStatus) -> None:
        sm = RunStateMachine("r1", RunStatus.WAITING)
        assert sm.transition(target) == target

    @pytest.mark.parametrize(
        "target", [RunStatus.RUNNING, RunStatus.FAILED]
    )
    def test_resuming_to(self, target: RunStatus) -> None:
        sm = RunStateMachine("r1", RunStatus.RESUMING)
        assert sm.transition(target) == target

    @pytest.mark.parametrize(
        "target", [RunStatus.CANCELLED, RunStatus.FAILED]
    )
    def test_cancelling_to(self, target: RunStatus) -> None:
        sm = RunStateMachine("r1", RunStatus.CANCELLING)
        assert sm.transition(target) == target

    def test_full_lifecycle(self) -> None:
        """完整生命周期：CREATED → QUEUED → RUNNING → COMPLETED。"""
        sm = RunStateMachine("r1", RunStatus.CREATED)
        assert sm.transition(RunStatus.QUEUED) == RunStatus.QUEUED
        assert sm.transition(RunStatus.RUNNING) == RunStatus.RUNNING
        assert sm.transition(RunStatus.COMPLETED) == RunStatus.COMPLETED
        assert sm.is_terminal

    def test_suspend_resume_lifecycle(self) -> None:
        """暂停恢复生命周期：RUNNING → WAITING → RESUMING → RUNNING → COMPLETED。"""
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        sm.transition(RunStatus.WAITING)
        sm.transition(RunStatus.RESUMING)
        sm.transition(RunStatus.RUNNING)
        sm.transition(RunStatus.COMPLETED)
        assert sm.is_terminal

    def test_cancel_lifecycle(self) -> None:
        """取消生命周期：RUNNING → CANCELLING → CANCELLED。"""
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        sm.transition(RunStatus.CANCELLING)
        sm.transition(RunStatus.CANCELLED)
        assert sm.is_terminal


# ─── 非法转换测试 ──────────────────────────────────────────


class TestIllegalTransitions:
    def test_created_to_running_rejected(self) -> None:
        """CREATED 不能直接到 RUNNING，必须经过 QUEUED。"""
        sm = RunStateMachine("r1", RunStatus.CREATED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            sm.transition(RunStatus.RUNNING)
        assert exc_info.value.current == RunStatus.CREATED
        assert exc_info.value.target == RunStatus.RUNNING

    def test_waiting_to_completed_rejected(self) -> None:
        """WAITING 不能直接到 COMPLETED，必须经过 RESUMING → RUNNING。"""
        sm = RunStateMachine("r1", RunStatus.WAITING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(RunStatus.COMPLETED)

    @pytest.mark.parametrize(
        "terminal",
        [RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.TERMINATED, RunStatus.FAILED],
    )
    def test_terminal_cannot_transition(self, terminal: RunStatus) -> None:
        """终态不能转换到任何状态。"""
        sm = RunStateMachine("r1", terminal)
        targets = [
            RunStatus.CREATED,
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING,
            RunStatus.RESUMING,
            RunStatus.CANCELLING,
        ]
        for target in targets:
            with pytest.raises(InvalidTransitionError):
                sm.transition(target)

    def test_queued_to_created_rejected(self) -> None:
        """不能回退到 CREATED。"""
        sm = RunStateMachine("r1", RunStatus.QUEUED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(RunStatus.CREATED)

    def test_running_to_queued_rejected(self) -> None:
        """不能回退到 QUEUED。"""
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(RunStatus.QUEUED)

    def test_resuming_to_waiting_rejected(self) -> None:
        """RESUMING 不能回退到 WAITING。"""
        sm = RunStateMachine("r1", RunStatus.RESUMING)
        with pytest.raises(InvalidTransitionError):
            sm.transition(RunStatus.WAITING)


# ─── 版本检查 ──────────────────────────────────────────────


class TestVersionCheck:
    def test_transition_increments_version(self) -> None:
        sm = RunStateMachine("r1", RunStatus.CREATED, version=0)
        assert sm.version == 0
        sm.transition(RunStatus.QUEUED)
        assert sm.version == 1
        sm.transition(RunStatus.RUNNING)
        assert sm.version == 2

    def test_version_match_passes(self) -> None:
        sm = RunStateMachine("r1", RunStatus.CREATED, version=5)
        sm.transition(RunStatus.QUEUED, expected_version=5)
        assert sm.version == 6

    def test_version_mismatch_raises(self) -> None:
        sm = RunStateMachine("r1", RunStatus.CREATED, version=5)
        with pytest.raises(VersionConflictError) as exc_info:
            sm.transition(RunStatus.QUEUED, expected_version=3)
        assert exc_info.value.run_id == "r1"
        assert exc_info.value.expected == 3
        assert exc_info.value.actual == 5

    def test_no_version_check_when_none(self) -> None:
        """expected_version 为 None 时跳过版本检查。"""
        sm = RunStateMachine("r1", RunStatus.CREATED, version=99)
        sm.transition(RunStatus.QUEUED)  # 不传 expected_version
        assert sm.version == 100


# ─── can_transition / get_allowed_transitions ──────────────


class TestQueryMethods:
    def test_can_transition_true(self) -> None:
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        assert sm.can_transition(RunStatus.COMPLETED) is True

    def test_can_transition_false(self) -> None:
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        assert sm.can_transition(RunStatus.CREATED) is False

    def test_get_allowed_transitions_running(self) -> None:
        sm = RunStateMachine("r1", RunStatus.RUNNING)
        allowed = sm.get_allowed_transitions()
        assert allowed == {
            RunStatus.WAITING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.TERMINATED,
        }

    def test_get_allowed_transitions_terminal(self) -> None:
        sm = RunStateMachine("r1", RunStatus.COMPLETED)
        assert sm.get_allowed_transitions() == set()

    def test_is_terminal_true(self) -> None:
        for status in [
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.TERMINATED,
            RunStatus.FAILED,
        ]:
            sm = RunStateMachine("r1", status)
            assert sm.is_terminal is True

    def test_is_terminal_false(self) -> None:
        for status in [
            RunStatus.CREATED,
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING,
            RunStatus.RESUMING,
            RunStatus.CANCELLING,
        ]:
            sm = RunStateMachine("r1", status)
            assert sm.is_terminal is False

    def test_is_active(self) -> None:
        for status in [
            RunStatus.CREATED,
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.WAITING,
            RunStatus.RESUMING,
            RunStatus.CANCELLING,
        ]:
            sm = RunStateMachine("r1", status)
            assert sm.is_active is True

    def test_is_active_terminal_false(self) -> None:
        for status in [
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.TERMINATED,
            RunStatus.FAILED,
        ]:
            sm = RunStateMachine("r1", status)
            assert sm.is_active is False


# ─── 崩溃恢复 ──────────────────────────────────────────────


class TestCrashRecovery:
    def test_recover_sets_status_directly(self) -> None:
        """recover 不检查转换合法性，直接设置状态。"""
        sm = RunStateMachine("r1", RunStatus.COMPLETED)  # 终态
        sm.recover(RunStatus.RUNNING)  # 直接恢复到 RUNNING
        assert sm.status == RunStatus.RUNNING

    def test_recover_does_not_increment_version(self) -> None:
        sm = RunStateMachine("r1", RunStatus.RUNNING, version=5)
        sm.recover(RunStatus.RUNNING)
        assert sm.version == 5  # 不递增

    def test_get_recovery_action_running(self) -> None:
        assert get_recovery_action(RunStatus.RUNNING) == "resume"

    def test_get_recovery_action_resuming(self) -> None:
        assert get_recovery_action(RunStatus.RESUMING) == "resume"

    def test_get_recovery_action_waiting(self) -> None:
        assert get_recovery_action(RunStatus.WAITING) == "wait"

    def test_get_recovery_action_cancelling(self) -> None:
        assert get_recovery_action(RunStatus.CANCELLING) == "continue_cancel"

    def test_get_recovery_action_terminal(self) -> None:
        for status in [
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.TERMINATED,
            RunStatus.FAILED,
        ]:
            assert get_recovery_action(status) == "none"

    def test_get_recovery_action_created(self) -> None:
        assert get_recovery_action(RunStatus.CREATED) == "none"

    def test_get_recovery_action_queued(self) -> None:
        assert get_recovery_action(RunStatus.QUEUED) == "none"
