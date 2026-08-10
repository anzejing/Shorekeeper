"""测试用 MCP 服务器。

提供 3 个简单工具用于测试 MCP 集成：
- echo: 回显输入文本
- add: 两数相加
- greet: 问候（带 enum 参数）

用法：python tests/fixtures/test_mcp_server.py
通过 stdio 传输运行。
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-mcp")


@mcp.tool()
def echo(text: str) -> str:
    """回显输入的文本。用于验证参数传递是否正确。"""
    return f"echo: {text}"


@mcp.tool()
def add(a: int, b: int) -> str:
    """计算两个整数的和。用于验证 integer 参数解析。"""
    result = a + b
    return f"{a} + {b} = {result}"


@mcp.tool()
def greet(name: str, style: str = "formal") -> str:
    """生成问候语。style 可选 'formal' 或 'casual'。用于验证 enum 参数。"""
    if style == "formal":
        return f"您好，{name}先生/女士。很高兴认识您。"
    elif style == "casual":
        return f"嘿 {name}！你好啊！"
    else:
        return f"你好，{name}！（风格: {style}）"


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run_stdio_async())
