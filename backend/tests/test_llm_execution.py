"""L3: LLM 执行度测试。

使用真实 LLM 调用验证 tool_search + tool_executor 两步调用模式。
测试场景：
1. LLM 能否通过 tool_search 发现 MCP 工具
2. LLM 能否通过 tool_executor 正确调用
3. LLM 能否处理参数错误并自行修正
4. LLM 能否连续调用多个工具

用法：python -m pytest tests/test_llm_execution.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from app.api.chat import _build_tool_directory, _BASE_SYSTEM_PROMPT
from app.mcp.models import MCPConfig, MCPServerConfig, MCPTransport
from app.mcp.service import MCPService
from app.runtime.litellm_client import (
    DONE,
    ERROR,
    TEXT_DELTA,
    TOOL_CALL_DELTA,
    USAGE,
    LiteLLMCompletionRequest,
    LiteLLMStreamEvent,
)
from app.runtime.models import (
    Message,
    Role,
    ToolCall,
    ToolDef,
    CancellationToken,
    Usage,
)
from app.runtime.native_litellm_client import NativeLiteLLMClient
from app.skill.service import SkillService
from app.tool.definitions import PROXY_TOOLS
from app.tool.index import ToolIndex, ToolIndexEntry
from app.tool.proxy_executor import ProxyToolExecutor
from app.tool.registry import ToolRegistry
from app.tool.schema_validator import SchemaValidator
from app.tool.search import ToolSearchExecutor

# 测试 MCP 服务器路径
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TEST_SERVER = _FIXTURES_DIR / "test_mcp_server.py"


@pytest.fixture
def venv_python() -> str:
    return str(Path(__file__).parent.parent / ".venv" / "bin" / "python")


@pytest.fixture
def llm_config() -> dict:
    """LLM 配置（opencode-go DeepSeek V4 Flash）。"""
    return {
        "model": "deepseek-v4-flash",
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "sk-FyvyyLijOk4MH5EEMT6TAPC2UhEJ4OyuDrhOyHscPGpcTjDhGKN4jpRdJNdUzpLP",
    }


@pytest_asyncio.fixture
async def test_env(venv_python: str):
    """创建完整测试环境。"""
    registry = ToolRegistry()
    index = ToolIndex()

    # 注册核心工具
    from app.tools import BUILTIN_TOOLS
    from app.tools.bash import BashExecutor
    from app.tools.file import ReadFileExecutor, WriteFileExecutor
    from app.memory.tools import MEMORY_TOOLS, MemoryToolExecutor

    registry.register(BUILTIN_TOOLS[0], BashExecutor())
    registry.register(BUILTIN_TOOLS[1], ReadFileExecutor())
    registry.register(BUILTIN_TOOLS[2], WriteFileExecutor())

    # 注册到 index
    for td in registry.get_all_tools():
        index.add(ToolIndexEntry(
            name=td.name, description=td.description,
            parameters=td.parameters, category="core", source="builtin",
        ))

    # 注册代理工具
    search_executor = ToolSearchExecutor(index)
    proxy_executor = ProxyToolExecutor(registry, SchemaValidator())
    from app.tool.definitions import TOOL_SEARCH_DEF, TOOL_EXECUTOR_DEF
    registry.register(TOOL_SEARCH_DEF, search_executor)
    registry.register(TOOL_EXECUTOR_DEF, proxy_executor)

    # MCP 服务器
    srv_name = f"test-mcp-{uuid.uuid4().hex[:8]}"
    config = MCPConfig(servers=[
        MCPServerConfig(
            name=srv_name, transport=MCPTransport.STDIO, enabled=True,
            command=venv_python, args=[str(_TEST_SERVER)], timeout=10,
        )
    ])
    mcp_service = MCPService(config, registry, index)
    await mcp_service.initialize()

    yield {
        "registry": registry,
        "index": index,
        "mcp_service": mcp_service,
        "search_executor": search_executor,
        "proxy_executor": proxy_executor,
        "server_name": srv_name,
    }

    await mcp_service.shutdown()
    await asyncio.sleep(0.3)


def _build_system_prompt(registry: ToolRegistry, srv_name: str) -> str:
    """构建固定 system prompt。"""
    # 固定工具列表（排除 MCP 动态工具，与 chat.py 渐进式披露设计一致）
    fixed_tools = [td for td in registry.get_all_tools() if "/" not in td.name]
    tool_dir = _build_tool_directory(fixed_tools)
    skill_summary = (
        "可用技能索引（调用 tool_search 搜索技能获取详细使用方法）：\n"
        f"- echo-test: 使用 {srv_name}/echo 工具回显文本\n"
        f"- math-test: 使用 {srv_name}/add 工具做加法"
    )
    return f"{_BASE_SYSTEM_PROMPT}\n\n{tool_dir}\n\n{skill_summary}"


async def _call_llm_with_tools(
    llm: NativeLiteLLMClient,
    messages: list[dict],
    tools: list[dict],
    model: str,
    extra: dict,
) -> tuple[str, list[ToolCall]]:
    """调用 LLM 并收集响应。"""
    request = LiteLLMCompletionRequest(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.1,
        max_tokens=2048,
        extra=extra,
    )

    text_parts = []
    tool_calls = {}
    cancellation = CancellationToken()

    async for event in llm.stream_completion(request, cancellation=cancellation):
        if event.type == TEXT_DELTA and event.content:
            text_parts.append(event.content)
        elif event.type == TOOL_CALL_DELTA:
            tc_id = event.tool_call_id or ""
            if tc_id not in tool_calls:
                tool_calls[tc_id] = {"id": tc_id, "name": event.tool_name or "", "args_parts": []}
            if event.tool_name:
                tool_calls[tc_id]["name"] = event.tool_name
            if event.arguments_delta:
                tool_calls[tc_id]["args_parts"].append(event.arguments_delta)

    parsed = []
    for tc in tool_calls.values():
        raw = "".join(tc["args_parts"])
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {"_raw": raw}
        parsed.append(ToolCall(tool_call_id=tc["id"], tool_name=tc["name"], arguments=args))

    return "".join(text_parts), parsed


async def _run_agent_loop(
    llm: NativeLiteLLMClient,
    system_prompt: str,
    user_message: str,
    registry: ToolRegistry,
    model: str,
    extra: dict,
    max_steps: int = 5,
) -> tuple[str, list[dict]]:
    """运行简化的 Agent Loop。

    返回 (最终回复, 工具调用记录)。
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": td.parameters,
            },
        }
        for td in registry.get_all_tools()
        if "/" not in td.name  # MCP 工具不直接暴露给 LLM（渐进式披露）
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    tool_log = []

    for step in range(max_steps):
        text, tool_calls = await _call_llm_with_tools(
            llm, messages, tools, model, extra
        )

        if not tool_calls:
            return text, tool_log

        # 记录 assistant 消息
        tc_data = [
            {
                "id": tc.tool_call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ]
        messages.append({
            "role": "assistant",
            "content": text or "",
            "tool_calls": tc_data,
        })

        # 执行工具
        for tc in tool_calls:
            result = await registry.execute(tc)
            content = "\n".join(
                p.text for p in result.content if hasattr(p, "text")
            )

            tool_log.append({
                "step": step,
                "tool": tc.tool_name,
                "args": tc.arguments,
                "is_error": result.is_error,
                "result_preview": content[:200],
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.tool_call_id,
                "content": content,
            })

    return "(超过最大步数)", tool_log


# ─── 测试用例 ─────────────────────────────────────────────


class TestLLMExecution:
    """L3: LLM 执行度测试。"""

    @pytest.mark.asyncio
    async def test_discover_and_call_echo(self, test_env, llm_config) -> None:
        """LLM 应能发现 echo 工具并正确调用。"""
        llm = NativeLiteLLMClient()
        registry = test_env["registry"]
        srv = test_env["server_name"]
        system = _build_system_prompt(registry, srv)

        reply, tool_log = await _run_agent_loop(
            llm, system,
            f"请使用 tool_search 搜索 echo 工具，然后用 tool_executor 调用 {srv}/echo 工具，输入文本 'hello world'",
            registry,
            llm_config["model"],
            {"base_url": llm_config["base_url"], "api_key": llm_config["api_key"]},
        )

        print(f"\n回复: {reply}")
        print(f"工具调用记录: {json.dumps(tool_log, ensure_ascii=False, indent=2)}")

        # 验证：应该调用了 tool_search 和 tool_executor
        tool_names = [t["tool"] for t in tool_log]
        assert "tool_search" in tool_names, f"LLM 未调用 tool_search，实际调用: {tool_names}"
        assert "tool_executor" in tool_names, f"LLM 未调用 tool_executor，实际调用: {tool_names}"

        # 验证：tool_executor 应该调用了 echo 工具
        echo_calls = [t for t in tool_log if t["tool"] == "tool_executor"]
        assert len(echo_calls) > 0
        assert echo_calls[0]["args"].get("tool_name") == f"{srv}/echo"
        assert not echo_calls[0]["is_error"], f"echo 执行失败: {echo_calls[0]['result_preview']}"

    @pytest.mark.asyncio
    async def test_direct_call_add(self, test_env, llm_config) -> None:
        """LLM 应能直接调用 tool_search + tool_executor 完成加法。"""
        llm = NativeLiteLLMClient()
        registry = test_env["registry"]
        srv = test_env["server_name"]
        system = _build_system_prompt(registry, srv)

        reply, tool_log = await _run_agent_loop(
            llm, system,
            f"请用 {srv}/add 工具计算 123 + 456 的结果。先搜索工具，再执行。",
            registry,
            llm_config["model"],
            {"base_url": llm_config["base_url"], "api_key": llm_config["api_key"]},
        )

        print(f"\n回复: {reply}")
        print(f"工具调用: {json.dumps(tool_log, ensure_ascii=False, indent=2)}")

        # 验证调用了 tool_executor
        tool_names = [t["tool"] for t in tool_log]
        assert "tool_executor" in tool_names

        # 验证参数正确
        executor_calls = [t for t in tool_log if t["tool"] == "tool_executor"]
        assert len(executor_calls) > 0
        args = executor_calls[0]["args"].get("arguments", {})
        assert args.get("a") == 123, f"参数 a 不正确: {args}"
        assert args.get("b") == 456, f"参数 b 不正确: {args}"
        assert not executor_calls[0]["is_error"]

    @pytest.mark.asyncio
    async def test_greet_with_enum(self, test_env, llm_config) -> None:
        """LLM 应能正确使用 enum 参数。"""
        llm = NativeLiteLLMClient()
        registry = test_env["registry"]
        srv = test_env["server_name"]
        system = _build_system_prompt(registry, srv)

        reply, tool_log = await _run_agent_loop(
            llm, system,
            f"请用 casual 风格通过 {srv}/greet 工具问候 Alice。先搜索工具了解参数格式，再执行。",
            registry,
            llm_config["model"],
            {"base_url": llm_config["base_url"], "api_key": llm_config["api_key"]},
        )

        print(f"\n回复: {reply}")
        print(f"工具调用: {json.dumps(tool_log, ensure_ascii=False, indent=2)}")

        # 验证调用了 greet 工具
        executor_calls = [t for t in tool_log if t["tool"] == "tool_executor"]
        assert len(executor_calls) > 0
        args = executor_calls[0]["args"].get("arguments", {})
        assert args.get("name") == "Alice"
        assert args.get("style") == "casual"
        assert not executor_calls[0]["is_error"]

    @pytest.mark.asyncio
    async def test_error_recovery(self, test_env, llm_config) -> None:
        """LLM 缺少必填参数时应能从错误消息中修正。"""
        llm = NativeLiteLLMClient()
        registry = test_env["registry"]
        srv = test_env["server_name"]
        system = _build_system_prompt(registry, srv)

        # 让 LLM 故意不传参数（通过提示让它犯错）
        reply, tool_log = await _run_agent_loop(
            llm, system,
            f"请直接调用 tool_executor 执行 {srv}/greet 工具，不要传任何参数，看看会发生什么。如果出错，请根据错误提示修正后重试。",
            registry,
            llm_config["model"],
            {"base_url": llm_config["base_url"], "api_key": llm_config["api_key"]},
        )

        print(f"\n回复: {reply}")
        print(f"工具调用: {json.dumps(tool_log, ensure_ascii=False, indent=2)}")

        # 验证：第一次应该失败，LLM 应该重试并成功
        tool_names = [t["tool"] for t in tool_log]
        executor_calls = [t for t in tool_log if t["tool"] == "tool_executor"]

        # 至少有一次失败
        has_error = any(t["is_error"] for t in executor_calls)
        # 至少有一次成功
        has_success = any(not t["is_error"] for t in executor_calls)

        assert has_error, "LLM 没有产生参数错误"
        assert has_success, "LLM 没有从错误中恢复"

    @pytest.mark.asyncio
    async def test_multiple_tools(self, test_env, llm_config) -> None:
        """LLM 能否连续调用多个不同工具。"""
        llm = NativeLiteLLMClient()
        registry = test_env["registry"]
        srv = test_env["server_name"]
        system = _build_system_prompt(registry, srv)

        reply, tool_log = await _run_agent_loop(
            llm, system,
            f"请完成以下任务：1) 用 {srv}/echo 回显 'task1 done'，2) 用 {srv}/add 记算 10+20，3) 用 {srv}/greet 以 casual 风格问候 Bob。每个工具调用前先用 tool_search 搜索。",
            registry,
            llm_config["model"],
            {"base_url": llm_config["base_url"], "api_key": llm_config["api_key"]},
            max_steps=10,
        )

        print(f"\n回复: {reply}")
        print(f"工具调用: {json.dumps(tool_log, ensure_ascii=False, indent=2)}")

        # 验证调用了3个不同的工具
        executor_calls = [t for t in tool_log if t["tool"] == "tool_executor"]
        called_tools = {t["args"].get("tool_name") for t in executor_calls}

        assert f"{srv}/echo" in called_tools, f"未调用 echo，实际: {called_tools}"
        assert f"{srv}/add" in called_tools, f"未调用 add，实际: {called_tools}"
        assert f"{srv}/greet" in called_tools, f"未调用 greet，实际: {called_tools}"

        # 全部成功
        for t in executor_calls:
            assert not t["is_error"], f"{t['args'].get('tool_name')} 执行失败: {t['result_preview']}"
