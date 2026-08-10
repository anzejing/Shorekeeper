"""tool_search 和 tool_executor 的 ToolDef 定义。

这两个工具是渐进式披露的核心代理工具：
- tool_search: 搜索可用工具，返回完整定义
- tool_executor: 通用执行器，路由到任意工具

注册到 ToolRegistry 后，由 Agent Loop 自然调用。
"""

from app.runtime.models import SideEffectLevel, ToolDef

TOOL_SEARCH_DEF = ToolDef(
    name="tool_search",
    description=(
        "搜索可用工具。当你需要执行某个操作但不确定是否有对应工具时调用。"
        "返回匹配工具的名称、描述和完整参数定义。"
        "使用 tool_executor 调用搜索到的工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "自然语言描述你需要的功能，"
                    "例如 '发送 Slack 消息'、'读取 GitHub PR'、'查询数据库'"
                ),
            },
            "category": {
                "type": "string",
                "description": "可选，按分类筛选：mcp（MCP 服务器工具）、skill（技能工具）、plugin（插件工具）",
                "enum": ["mcp", "skill", "plugin"],
            },
        },
        "required": ["query"],
    },
    side_effect_level=SideEffectLevel.READ_ONLY,
)

TOOL_EXECUTOR_DEF = ToolDef(
    name="tool_executor",
    description=(
        "执行任意已注册工具。"
        "先用 tool_search 获取工具定义和参数格式，再调用本工具执行。"
        "tool_name 必须填完整工具名（如 bash_execute、github/list_repos）。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "要执行的工具名称，必须是 tool_search 返回的完整名称",
            },
            "arguments": {
                "type": "object",
                "description": (
                    "工具参数，必须严格匹配该工具的参数定义"
                    "（参见 tool_search 返回的参数说明）"
                ),
            },
        },
        "required": ["tool_name", "arguments"],
    },
    side_effect_level=SideEffectLevel.EXTERNAL_MUTATION,
)

# 代理工具列表
PROXY_TOOLS: list[ToolDef] = [TOOL_SEARCH_DEF, TOOL_EXECUTOR_DEF]
