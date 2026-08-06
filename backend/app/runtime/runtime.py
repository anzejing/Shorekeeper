"""NativePythonRuntime — AgentRuntimeAdapter 的实现。

组装层：把 Agent Loop + LiteLLM + ToolExecutor + Interceptor
+ EventPublisher + CheckpointStore 串起来。

职责：
1. 创建 Run（RunSnapshot + 状态机）
2. 启动执行（状态转 RUNNING → 启动 Agent Loop）
3. 暂停/恢复（SuspendDecision → WAITING → resume → RUNNING）
4. 取消（CancellationToken → CANCELLING → CANCELLED）
5. 查询状态
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.runtime.checkpoint import CheckpointStore
from app.runtime.event_publisher import EventPublisher
from app.runtime.events import (
    RunCancelled,
    RunCancellationRequested,
    RunCompleted,
    RunCreated,
    RunFailed,
    RunResumed,
    RunStarted,
    RunStateChanged,
    RunTerminated,
    create_event,
)
from app.runtime.litellm_client import LiteLLMClient
from app.runtime.loop import RunContext, run_loop
from app.runtime.models import (
    CancellationToken,
    Message,
    ResumeInput,
    Role,
    RunHandle,
    RunId,
    RunRequest,
    RunSnapshot,
    RunStatus,
    Usage,
    new_run_id,
)
from app.runtime.run_store import RunStore
from app.runtime.state import (
    InvalidTransitionError,
    RunStateMachine,
    VersionConflictError,
)

# ─── 异常 ─────────────────────────────────────────────────


class RunNotFoundError(Exception):
    """Run 不存在。"""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run 不存在: {run_id}")
        self.run_id = run_id


class RunAlreadyCancellingError(Exception):
    """Run 正在取消中，无法恢复。"""


# ─── NativePythonRuntime ─────────────────────────────────


class NativePythonRuntime:
    """Runtime 组装层。

    把所有组件串起来，对外提供 Run 生命周期管理。
    """

    def __init__(
        self,
        llm: LiteLLMClient,
        tool_executor: Any,  # ToolExecutor Protocol
        interceptor: Any,  # InterceptorChain Protocol
        publisher: EventPublisher,
        run_store: RunStore,
        checkpoint_store: CheckpointStore,
        *,
        event_store: Any = None,  # SQLiteEventStore（可选，用于事件查询）
        default_model: str = "",
        default_max_steps: int = 20,
        llm_extra: dict[str, Any] | None = None,  # LLM provider-specific 配置
    ) -> None:
        self._llm = llm
        self._tool_executor = tool_executor
        self._interceptor = interceptor
        self._publisher = publisher
        self._run_store = run_store
        self._checkpoint_store = checkpoint_store
        self._event_store = event_store
        self._default_model = default_model
        self._default_max_steps = default_max_steps
        self._llm_extra = llm_extra or {}

        # 运行中的 Run：run_id → (task, cancellation_token)
        self._active: dict[str, tuple[asyncio.Task, CancellationToken]] = {}
        # 每个 Run 注入的 tools
        self._run_tools: dict[str, list] = {}
        # 执行/恢复的并发保护锁（防止同一 run 被并发执行两次）
        self._execution_locks: dict[str, asyncio.Lock] = {}

    async def create_run(self, request: RunRequest) -> RunHandle:
        """创建 Run。"""
        run_id = new_run_id()
        now = datetime.now(timezone.utc)

        snapshot = RunSnapshot(
            run_id=run_id,
            session_id=request.session_id,
            agent_id=request.agent_id,
            status=RunStatus.CREATED,
            version=0,
            messages=list(request.messages),
            current_step=0,
            max_steps=request.max_steps or self._default_max_steps,
            usage=Usage(),
            suspension_id=None,
            execution_attempt=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
            metadata=request.metadata,
        )

        await self._run_store.save(snapshot)
        await self._publisher.publish(
            create_event(
                RunCreated,
                run_id=run_id,
                session_id=request.session_id,
                sequence=0,
                agent_id=request.agent_id,
                metadata=request.metadata,
            )
        )

        # 存储该 Run 注入的 tools
        if request.tools:
            self._run_tools[run_id] = list(request.tools)

        return RunHandle(
            run_id=run_id,
            status=RunStatus.CREATED,
            created_at=now,
        )

    async def execute(self, run_id: RunId) -> None:
        """启动 Run 执行。"""
        lock = self._execution_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            await self._execute_locked(run_id)

    async def _execute_locked(self, run_id: RunId) -> None:
        """execute 的临界区实现（调用方须持有 per-run 锁）。"""
        snapshot = await self._get_snapshot(run_id)

        # 状态机检查
        sm = RunStateMachine(run_id, snapshot.status, snapshot.version)

        if sm.status == RunStatus.RUNNING:
            # 已在运行，忽略
            return

        # 状态转换：CREATED → QUEUED → RUNNING（内存中连续转换，一次保存）
        expected_version = snapshot.version
        if sm.can_transition(RunStatus.QUEUED):
            sm.transition(RunStatus.QUEUED, expected_version=expected_version)
            expected_version = sm.version
        sm.transition(RunStatus.RUNNING, expected_version=expected_version)

        snapshot.status = RunStatus.RUNNING
        snapshot.version = sm.version
        await self._run_store.save(snapshot)
        await self._publish_state_change(run_id, snapshot.session_id, "created", "running")

        # 同步拦截器上下文（run_id / session_id 等）
        await self._sync_interceptor_context(snapshot)

        # 创建 CancellationToken 并启动 Agent Loop
        cancellation = CancellationToken()
        ctx = RunContext(
            run_id=run_id,
            session_id=snapshot.session_id,
            agent_id=snapshot.agent_id,
            messages=list(snapshot.messages),
            tools=self._run_tools.get(run_id, []),
            max_steps=snapshot.max_steps,
            llm=self._llm,
            tool_executor=self._tool_executor,
            interceptor=self._interceptor,
            publisher=self._publisher,
            checkpoint_store=self._checkpoint_store,
            model=self._default_model,
            cancellation=cancellation,
            usage=snapshot.usage,
            metadata=snapshot.metadata,
            llm_extra=dict(self._llm_extra),
        )

        task = asyncio.create_task(self._run_agent_loop(ctx, snapshot))
        self._active[run_id] = (task, cancellation)

    async def _run_agent_loop(
        self, ctx: RunContext, snapshot: RunSnapshot
    ) -> None:
        """执行 Agent Loop 并处理完成状态。"""
        try:
            result = await run_loop(ctx)

            # 更新最终状态和消息
            snapshot = await self._run_store.get(RunId(ctx.run_id))
            if snapshot and snapshot.status == RunStatus.RUNNING:
                if result and result.suspended:
                    # 暂停状态
                    snapshot.status = RunStatus.WAITING
                    snapshot.suspension_id = result.suspension_id
                else:
                    # 正常完成
                    snapshot.status = RunStatus.COMPLETED
                    snapshot.completed_at = datetime.now(timezone.utc)
                snapshot.messages = list(ctx.messages)
                await self._run_store.save(snapshot)

        except Exception:
            # run_loop 内部已发布 RunFailed 事件
            snapshot = await self._run_store.get(RunId(ctx.run_id))
            if snapshot and snapshot.status == RunStatus.RUNNING:
                snapshot.status = RunStatus.FAILED
                snapshot.messages = list(ctx.messages)
                snapshot.completed_at = datetime.now(timezone.utc)
                await self._run_store.save(snapshot)
        finally:
            self._active.pop(ctx.run_id, None)

    async def resume(self, run_id: RunId, resume_input: ResumeInput) -> RunHandle:
        """恢复暂停的 Run。"""
        snapshot = await self._get_snapshot(run_id)
        sm = RunStateMachine(run_id, snapshot.status, snapshot.version)

        if sm.status == RunStatus.CANCELLING:
            raise RunAlreadyCancellingError(f"Run {run_id} 正在取消中")

        # 状态转换：WAITING → RESUMING → RUNNING（内存中连续转换，一次保存）
        expected_version = snapshot.version
        sm.transition(RunStatus.RESUMING, expected_version=expected_version)
        expected_version = sm.version
        sm.transition(RunStatus.RUNNING, expected_version=expected_version)

        snapshot.status = RunStatus.RUNNING
        snapshot.version = sm.version
        await self._run_store.save(snapshot)

        # 同步拦截器上下文（run_id / session_id 等）
        await self._sync_interceptor_context(snapshot)

        # 发布恢复事件
        await self._publisher.publish(
            create_event(
                RunResumed,
                run_id=run_id,
                session_id=snapshot.session_id,
                sequence=snapshot.current_step,
                suspension_id=snapshot.suspension_id or "",
                idempotency_key=resume_input.idempotency_key,
            )
        )

        # 重新启动 Agent Loop
        cancellation = CancellationToken()
        ctx = RunContext(
            run_id=run_id,
            session_id=snapshot.session_id,
            agent_id=snapshot.agent_id,
            messages=list(snapshot.messages),
            tools=self._run_tools.get(run_id, []),
            max_steps=snapshot.max_steps,
            llm=self._llm,
            tool_executor=self._tool_executor,
            interceptor=self._interceptor,
            publisher=self._publisher,
            checkpoint_store=self._checkpoint_store,
            model=self._default_model,
            cancellation=cancellation,
            usage=snapshot.usage,
            llm_extra=dict(self._llm_extra),
        )

        task = asyncio.create_task(self._run_agent_loop(ctx, snapshot))
        self._active[run_id] = (task, cancellation)

        return RunHandle(
            run_id=run_id,
            status=RunStatus.RUNNING,
            created_at=snapshot.created_at,
        )

    async def cancel(self, run_id: RunId, *, reason: str | None = None) -> None:
        """取消 Run。"""
        snapshot = await self._get_snapshot(run_id)
        sm = RunStateMachine(run_id, snapshot.status, snapshot.version)

        if sm.is_terminal:
            return  # 终态，忽略

        # 状态转换：→ CANCELLING
        if sm.can_transition(RunStatus.CANCELLING):
            sm.transition(RunStatus.CANCELLING, expected_version=snapshot.version)
            snapshot.status = RunStatus.CANCELLING
            snapshot.version = sm.version
            await self._run_store.save(snapshot)

            await self._publisher.publish(
                create_event(
                    RunCancellationRequested,
                    run_id=run_id,
                    session_id=snapshot.session_id,
                    sequence=snapshot.current_step,
                    reason=reason,
                )
            )

            # 触发 CancellationToken
            if run_id in self._active:
                _, cancellation = self._active[run_id]
                cancellation.cancel(reason or "用户取消")

            # 等待任务完成或直接标记取消
            if run_id in self._active:
                task, _ = self._active[run_id]
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            # 确保最终状态
            snapshot = await self._run_store.get(RunId(run_id))
            if snapshot and snapshot.status == RunStatus.CANCELLING:
                snapshot.status = RunStatus.CANCELLED
                snapshot.completed_at = datetime.now(timezone.utc)
                await self._run_store.save(snapshot)
                await self._publisher.publish(
                    create_event(
                        RunCancelled,
                        run_id=run_id,
                        session_id=snapshot.session_id,
                        sequence=snapshot.current_step,
                        reason=reason,
                    )
                )

    async def terminate(self, run_id: RunId, *, reason: str) -> None:
        """硬杀 Run。"""
        snapshot = await self._get_snapshot(run_id)
        sm = RunStateMachine(run_id, snapshot.status, snapshot.version)

        if sm.is_terminal:
            return

        if sm.can_transition(RunStatus.TERMINATED):
            sm.transition(RunStatus.TERMINATED, expected_version=snapshot.version)
            snapshot.status = RunStatus.TERMINATED
            snapshot.completed_at = datetime.now(timezone.utc)
            snapshot.version = sm.version
            await self._run_store.save(snapshot)

            # 取消任务
            if run_id in self._active:
                task, cancellation = self._active.pop(run_id)
                cancellation.cancel(reason)
                task.cancel()

            await self._publisher.publish(
                create_event(
                    RunTerminated,
                    run_id=run_id,
                    session_id=snapshot.session_id,
                    sequence=snapshot.current_step,
                    reason=reason,
                )
            )

    async def get_run(self, run_id: RunId) -> RunSnapshot:
        """获取 Run 快照。"""
        return await self._get_snapshot(run_id)

    async def execute_and_wait(
        self, run_id: RunId, timeout: float = 120.0
    ) -> RunSnapshot:
        """启动执行并等待完成。

        Args:
            run_id: Run ID。
            timeout: 超时秒数。

        Returns:
            完成后的 RunSnapshot。

        Raises:
            asyncio.TimeoutError: 超时。
            RunNotFoundError: Run 不存在。
        """
        await self.execute(run_id)

        # 等待 task 完成
        if run_id in self._active:
            task, _ = self._active[run_id]
            try:
                await asyncio.wait_for(task, timeout=timeout)
            except asyncio.TimeoutError:
                await self.cancel(run_id, reason="执行超时")
                raise

        return await self._get_snapshot(run_id)

    async def wait_until_terminal(
        self, run_id: RunId, timeout: float = 300.0
    ) -> RunSnapshot:
        """等待 Run 到达终态（含挂起 → resume 的多次执行）。

        场景：run 因审批挂起后由 resume API 恢复执行，
        本方法会持续等待直到 run 进入终态（completed / failed / cancelled）。
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if asyncio.get_event_loop().time() > deadline:
                raise asyncio.TimeoutError(f"Run {run_id} 等待超时")

            snapshot = await self._get_snapshot(run_id)
            sm = RunStateMachine(run_id, snapshot.status, snapshot.version)
            if sm.is_terminal:
                return snapshot

            task, _ = self._active.get(run_id, (None, None))
            if task is not None:
                # 有活跃 task（首次执行或 resume 后）→ 等待完成。
                # 注意：不能用 wait_for（超时会取消 task），用 asyncio.wait 只等待不取消。
                try:
                    done, _ = await asyncio.wait({task}, timeout=10.0)
                except asyncio.TimeoutError:
                    continue
                if task not in done:
                    continue  # 任务仍在运行，继续等待
                self._active.pop(run_id, None)
                continue

            # 无活跃 task 且非终态（WAITING 挂起中）→ 等待 resume
            await asyncio.sleep(1.0)

    # ─── 内部辅助 ─────────────────────────────────────────

    async def _sync_interceptor_context(self, snapshot: RunSnapshot) -> None:
        """同步 PermissionInterceptor 的 run 上下文。

        interceptor 创建审批时需要 run_id / session_id，
        这些值在每次 execute / resume 时必须更新。
        """
        interceptor = self._interceptor
        update = getattr(interceptor, "update_run_context", None)
        if update is not None:
            update(
                run_id=snapshot.run_id,
                session_id=snapshot.session_id,
                run_version=snapshot.version,
                execution_revision=snapshot.execution_attempt,
            )

    async def _get_snapshot(self, run_id: str) -> RunSnapshot:
        """获取 Run 快照，不存在则抛异常。"""
        snapshot = await self._run_store.get(RunId(run_id))
        if snapshot is None:
            raise RunNotFoundError(run_id)
        return snapshot

    async def _publish_state_change(
        self,
        run_id: str,
        session_id: str,
        old_status: str,
        new_status: str,
    ) -> None:
        """发布状态变更事件。"""
        await self._publisher.publish(
            create_event(
                RunStateChanged,
                run_id=run_id,
                session_id=session_id,
                sequence=0,
                old_status=old_status,
                new_status=new_status,
            )
        )
