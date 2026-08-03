"""通用 Tools 模块。

提供 bash_execute, read_file, write_file 三个基础工具。
"""

from app.runtime.models import SideEffectLevel, ToolDef

# ─── Tool 定义 ────────────────────────────────────────────

BASH_EXECUTE_TOOL = ToolDef(
    name="bash_execute",
    description=(
        "在 shell 中执行命令。支持管道、重定向、复合命令。"
        "注意：命令会经过权限检查，敏感操作需要用户审批。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令。",
            },
        },
        "required": ["command"],
    },
    side_effect_level=SideEffectLevel.EXTERNAL_MUTATION,
    timeout=30.0,
)

READ_FILE_TOOL = ToolDef(
    name="read_file",
    description=(
        "读取文件内容。返回指定行范围的内容。"
        "用于查看代码、配置文件、日志等。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（绝对或相对路径）。",
            },
            "offset": {
                "type": "integer",
                "default": 0,
                "description": "起始行号（从 0 开始）。",
            },
            "limit": {
                "type": "integer",
                "default": 200,
                "description": "最大读取行数。",
            },
        },
        "required": ["path"],
    },
    side_effect_level=SideEffectLevel.READ_ONLY,
)

WRITE_FILE_TOOL = ToolDef(
    name="write_file",
    description=(
        "写入文件内容。如果文件不存在则创建，存在则覆盖。"
        "注意：覆盖写入，不会保留原内容。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径（绝对或相对路径）。",
            },
            "content": {
                "type": "string",
                "description": "要写入的内容。",
            },
        },
        "required": ["path", "content"],
    },
    side_effect_level=SideEffectLevel.LOCAL_MUTATION,
)


# ─── Tool 列表 ────────────────────────────────────────────

BUILTIN_TOOLS: list[ToolDef] = [
    BASH_EXECUTE_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
]
