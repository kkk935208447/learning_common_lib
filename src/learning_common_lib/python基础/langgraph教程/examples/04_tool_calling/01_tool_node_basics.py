"""
04_tool_calling / 01_tool_node_basics

目标:
    演示 @tool 定义、手动执行 tool_call，以及在 StateGraph 中集成 ToolNode

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    @tool, ChatModel.bind_tools, ToolNode

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/04_tool_calling/01_tool_node_basics.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/04_tool_calling/01_tool_node_basics.py

预期现象:
    1. 打印工具 schema（JSON 格式）
    2. FakeLLM 返回带 tool_calls 的 AIMessage
    3. 手动执行 tool_call，理解底层消息结构
    4. 在 StateGraph 中集成 ToolNode，展示生产中的常见写法

生产提醒:
    - 真实场景请替换 FakeListChatModel 为 ChatOpenAI / ChatAnthropic
    - @tool 的 docstring 会作为工具描述传给 LLM，务必写清楚
"""
from __future__ import annotations

import asyncio
import json
import ast
from typing import Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


# ── 1. 定义工具 ──────────────────────────────────────────────
@tool
def search(query: str) -> str:
    """搜索工具：根据关键词返回搜索结果"""
    return f"搜索结果: {query} -> LangGraph 是一个用于构建有状态 Agent 的框架"


@tool
def calculator(expression: str) -> str:
    """计算器工具：计算数学表达式并返回结果"""
    allowed_binops = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
    }
    allowed_unary = {
        ast.UAdd: lambda a: a,
        ast.USub: lambda a: -a,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binops:
            left = eval_node(node.left)
            right = eval_node(node.right)
            return allowed_binops[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary:
            operand = eval_node(node.operand)
            return allowed_unary[type(node.op)](operand)
        raise ValueError("仅支持加减乘除和数字常量")

    parsed = ast.parse(expression, mode="eval")
    result = eval_node(parsed)
    if result.is_integer():
        return str(int(result))
    return str(result)


tools = [search, calculator]
tool_map = {tool_.name: tool_ for tool_ in tools}


async def main() -> None:
    # ── 2. 查看自动生成的工具 schema ─────────────────────────
    print("=== 工具 Schema ===")
    for t in tools:
        print(json.dumps(t.tool_call_schema.model_json_schema(), indent=2, ensure_ascii=False))

    # ── 3. 构造模拟的 AIMessage（含 tool_calls）──────────────
    # 真实场景中这一步由 LLM 完成：llm_with_tools = llm.bind_tools(tools)
    # 使用 FakeListChatModel 时需要手动构造 tool_calls 来模拟 LLM 输出
    fake_ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_001",
                "name": "search",
                "args": {"query": "LangGraph 是什么"},
            },
            {
                "id": "call_002",
                "name": "calculator",
                "args": {"expression": "3 + 4 * 5"},
            },
        ],
    )
    print("\n=== 模拟 LLM 返回的 AIMessage ===")
    print(f"tool_calls 数量: {len(fake_ai_message.tool_calls)}")
    for tc in fake_ai_message.tool_calls:
        print(f"  - {tc['name']}({tc['args']})")

    # ── 4. 手动执行 tool_calls，理解底层消息结构 ──────────────
    print("\n=== 手动执行 tool_calls ===")
    manual_tool_messages: list[ToolMessage] = []
    for tool_call in fake_ai_message.tool_calls:
        tool_ = tool_map[tool_call["name"]]
        content = tool_.invoke(tool_call["args"])
        tool_message = ToolMessage(
            content=str(content),
            name=tool_.name,
            tool_call_id=tool_call["id"],
        )
        manual_tool_messages.append(tool_message)
        print(f"  工具: {tool_message.name} | 结果: {tool_message.content}")

    # ── 5. 在 StateGraph 中使用 ToolNode ─────────────────────
    print("\n=== 在 StateGraph 中集成 ToolNode ===")

    def fake_llm_node(state: MessagesState) -> dict:
        """模拟 LLM 节点：返回带 tool_calls 的消息"""
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_graph_001",
                            "name": "search",
                            "args": {"query": "StateGraph 用法"},
                        }
                    ],
                )
            ]
        }

    def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("llm", fake_llm_node)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue)
    graph.add_edge("tools", END)

    app = graph.compile()
    output = await app.ainvoke({"messages": []})
    for msg in output["messages"]:
        payload = msg.content or msg.tool_calls
        print(f"  [{type(msg).__name__}] {payload}")


if __name__ == "__main__":
    asyncio.run(main())
