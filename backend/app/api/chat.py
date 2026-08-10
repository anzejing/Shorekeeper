"""对话 API。

提供同步和流式两种对话方式：
- POST /api/chat — 同步，等待完成后返回
- POST /api/chat/stream — 流式，立即返回 run_id，前端通过 SSE 接收事件
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.runtime import get_runtime
from app.runtime.models import (
    Message,
    Role,
    RunRequest,
    RunStatus,
    Usage,
)
from app.memory.service import MemoryService
from app.skill.service import SkillService
from app.tool.definitions import PROXY_TOOLS
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


# --- 请求/响应模型 ---


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


class ChatStreamResponse(BaseModel):
    """流式对话响应——立即返回 run_id。"""

    run_id: str
    session_id: str


# --- 基础系统提示 ---

_BASE_SYSTEM_PROMPT = (
    "你是一个有用的 AI 助手。你可以使用工具来完成任务。\n\n"
    "当用户的需求涉及你无法直接完成的操作时，使用可用的工具。\n"
    "对于核心工具（bash_execute, read_file, write_file, read_memory, "
    "write_memory, search_memory），直接调用。\n"
    "对于其他工具，先用 tool_search 搜索，再用 tool_executor 执行。"
)


# --- 通用会话准备逻辑 ---


def _build_tool_directory(registry: ToolRegistry) -> str:
    """构建工具目录（固定文本，注入 system）。

    核心工具列出完整信息，代理工具说明使用方式。
    """
    lines = ["## 可用工具\n", "你可以直接使用以下工具（直接调用，无需搜索）：\n"]

    # 核心工具（排除代理工具）
    proxy_names = {t.name for t in PROXY_TOOLS}
    core_tools = [
        td for td in registry.get_all_tools()
        if td.name not in proxy_names
    ]
    for td in core_tools:
        lines.append(f"- {td.name}: {td.description}")

    lines.append("")
    lines.append("当你需要执行上述工具之外的操作时：")
    lines.append("1. 先调用 tool_search(query=\"你需要的功能\") 搜索工具")
    lines.append("2. 阅读返回的工具定义和参数格式")
    lines.append("3. 调用 tool_executor(tool_name=\"工具名\", arguments={...}) 执行")

    return "\n".join(lines)


async def _prepare_session_and_run(
    request: ChatRequest,
) -> tuple[str, str]:
    """获取或创建会话、保存用户消息、组装 Run 并创建。

    返回 (session_id, run_id)。
    """
    memory = _get_memory()
    skill = _get_skill()
    runtime = get_runtime()
    registry = _get_registry()

    # 1. 获取或创建 session
    session_id = request.session_id
    if session_id:
        session = await memory.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"会话不存在: {session_id}"
            )
    else:
        title = request.message[:20] + ("..." if len(request.message) > 20 else "")
        session_resp = await memory.create_session(title=title)
        session_id = session_resp.session_id

    # 2. 保存用户消息
    await memory.add_message(session_id, "user", request.message)

    # 3. 获取历史上下文
    context = await memory.get_context(
        session_id, max_messages=_MAX_CONTEXT_MESSAGES
    )

    # 4. 组装固定 system prompt（永远不变）
    tool_directory = _build_tool_directory(registry)
    skill_summaries = await skill.get_skill_summaries()

    system_parts = [_BASE_SYSTEM_PROMPT, tool_directory]
    if skill_summaries:
        system_parts.append(skill_summaries)

    system_message = Message(
        role=Role.SYSTEM,
        content="\n\n".join(system_parts),
    )

    # 5. 组装 messages
    messages: list[Message] = [system_message]
    for msg in context:
        try:
            role = Role(msg.role)
        except ValueError:
            continue
        messages.append(Message(role=role, content=msg.content))

    # 6. 固定 tools 列表（永远不变）
    tools = registry.get_all_tools()

    # 7. 创建 Run
    run_request = RunRequest(
        session_id=session_id,
        agent_id="chat",
        messages=messages,
        tools=tools,
        max_steps=10,
    )
    handle = await runtime.create_run(run_request)

    return session_id, handle.run_id


async def _save_reply_after_run(
    runtime: Any,
    session_id: str,
    run_id: str,
    timeout: float = _RUN_TIMEOUT,
) -> str:
    """等待 Run 完成并保存 assistant 回复。返回回复文本。"""
    memory = _get_memory()

    try:
        snapshot = await runtime.execute_and_wait(run_id, timeout=timeout)
    except Exception as e:
        log.exception("Run 执行失败: %s", run_id)
        raise

    reply = _extract_reply(snapshot.messages)
    if reply:
        await memory.add_message(session_id, "assistant", reply)

    return reply


# --- API 端点 ---


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """发送消息并获取回复（同步）。

    完整数据流：
    1. 获取或创建 session
    2. 保存用户消息
    3. 获取历史上下文
    4. 收集 system prompts
    5. 组装 messages -> 创建 Run -> 执行
    6. 保存 assistant 回复
    7. 返回结果
    """
    runtime = get_runtime()

    session_id, run_id = await _prepare_session_and_run(request)

    try:
        reply = await _save_reply_after_run(runtime, session_id, run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")

    snapshot = await runtime.get_run(run_id)

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        run_id=run_id,
        usage=snapshot.usage,
    )


@router.post("/stream", response_model=ChatStreamResponse)
async def chat_stream(request: ChatRequest) -> ChatStreamResponse:
    """发送消息，立即返回 run_id（流式）。

    前端随后连接 GET /api/runs/{run_id}/stream 接收 SSE 事件。
    Run 完成后后端自动保存 assistant 回复。
    """
    runtime = get_runtime()

    session_id, run_id = await _prepare_session_and_run(request)

    # 后台监听：等待 Run 到达终态（含挂起→resume）后保存 assistant 回复
    async def _wait_and_save():
        try:
            # 等待 Run 完成（最多 10 分钟；挂起等待审批期间会持续等待）
            snapshot = await runtime.wait_until_terminal(run_id, timeout=600.0)
            reply = _extract_reply(snapshot.messages)
            if reply:
                await _get_memory().add_message(session_id, "assistant", reply)
        except Exception:
            log.exception("后台保存回复失败: %s", run_id)

    # 启动执行（唯一入口，避免双重执行）
    await runtime.execute(run_id)

    # 启动后台等待任务
    asyncio.create_task(_wait_and_save())

    return ChatStreamResponse(run_id=run_id, session_id=session_id)


# --- 辅助 ---


def _extract_reply(messages: list[Message]) -> str:
    """从 Run 的消息列表中提取最后一条 assistant 回复。"""
    for msg in reversed(messages):
        if msg.role == Role.ASSISTANT:
            if isinstance(msg.content, str):
                return msg.content
            if isinstance(msg.content, list):
                texts = []
                for part in msg.content:
                    if hasattr(part, "text"):
                        texts.append(part.text)
                if texts:
                    return "\n".join(texts)
    return ""
