"""最小对话 API。

验证 Memory + Skill + Runtime 的完整数据流。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.runtime import get_runtime
from app.memory.service import MemoryService
from app.runtime.models import (
    Message,
    Role,
    RunRequest,
    RunStatus,
    Usage,
)
from app.skill.service import SkillService
from app.tool.registry import ToolRegistry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 依赖由 main.py 注入
_memory_service: MemoryService | None = None
_skill_service: SkillService | None = None
_tool_registry: ToolRegistry | None = None

# 配置
_MAX_CONTEXT_MESSAGES = 50
_RUN_TIMEOUT = 120.0


def init_chat_api(
    memory_service: MemoryService,
    skill_service: SkillService,
    tool_registry: ToolRegistry,
) -> None:
    """初始化 Chat API。"""
    global _memory_service, _skill_service, _tool_registry
    _memory_service = memory_service
    _skill_service = skill_service
    _tool_registry = tool_registry


def _get_memory() -> MemoryService:
    if _memory_service is None:
        raise HTTPException(status_code=503, detail="Memory 模块未初始化")
    return _memory_service


def _get_skill() -> SkillService:
    if _skill_service is None:
        raise HTTPException(status_code=503, detail="Skill 模块未初始化")
    return _skill_service


def _get_registry() -> ToolRegistry:
    if _tool_registry is None:
        raise HTTPException(status_code=503, detail="ToolRegistry 未初始化")
    return _tool_registry


# ─── 请求/响应模型 ────────────────────────────────────────


class ChatRequest(BaseModel):
    """对话请求。"""

    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    """对话响应。"""

    reply: str
    session_id: str
    run_id: str
    usage: Usage


# ─── API 端点 ─────────────────────────────────────────────


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """发送消息并获取回复。

    完整数据流：
    1. 获取或创建 session
    2. 保存用户消息
    3. 获取历史上下文
    4. 收集 system prompts
    5. 组装 messages → 创建 Run → 执行
    6. 保存 assistant 回复
    7. 返回结果
    """
    memory = _get_memory()
    skill = _get_skill()
    runtime = get_runtime()
    registry = _get_registry()

    # ── 1. 获取或创建 session ──
    session_id = request.session_id
    if session_id:
        session = await memory.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"会话不存在: {session_id}"
            )
    else:
        # 自动生成标题（取消息前 20 字）
        title = request.message[:20] + ("..." if len(request.message) > 20 else "")
        session_resp = await memory.create_session(title=title)
        session_id = session_resp.session_id

    # ── 2. 保存用户消息 ──
    await memory.add_message(session_id, "user", request.message)

    # ── 3. 获取历史上下文 ──
    context = await memory.get_context(
        session_id, max_messages=_MAX_CONTEXT_MESSAGES
    )

    # ── 4. 收集 system prompts ──
    system_prompts = await skill.get_system_prompts()

    # ── 5. 组装 messages ──
    messages: list[Message] = []

    # system prompts
    for prompt in system_prompts:
        messages.append(Message(role=Role.SYSTEM, content=prompt))

    # 历史消息
    for msg in context:
        try:
            role = Role(msg.role)
        except ValueError:
            continue
        messages.append(Message(role=role, content=msg.content))

    # ── 6. 创建 Run 并执行 ──
    tools = registry.get_all_tools()

    run_request = RunRequest(
        session_id=session_id,
        agent_id="chat",
        messages=messages,
        tools=tools,
        max_steps=10,
    )

    handle = await runtime.create_run(run_request)
    run_id = handle.run_id

    try:
        snapshot = await runtime.execute_and_wait(
            run_id, timeout=_RUN_TIMEOUT
        )
    except Exception as e:
        log.exception("Run 执行失败: %s", run_id)
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")

    # ── 7. 提取 assistant 回复 ──
    reply = _extract_reply(snapshot.messages)

    # ── 8. 保存 assistant 回复 ──
    if reply:
        await memory.add_message(session_id, "assistant", reply)

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        run_id=run_id,
        usage=snapshot.usage,
    )


# ─── 辅助 ─────────────────────────────────────────────────


def _extract_reply(messages: list[Message]) -> str:
    """从 Run 的消息列表中提取最后一条 assistant 回复。"""
    for msg in reversed(messages):
        if msg.role == Role.ASSISTANT:
            if isinstance(msg.content, str):
                return msg.content
            # 如果是 list[ContentPart]，提取 text
            if isinstance(msg.content, list):
                texts = []
                for part in msg.content:
                    if hasattr(part, "text"):
                        texts.append(part.text)
                if texts:
                    return "\n".join(texts)
    return ""
