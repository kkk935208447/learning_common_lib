from __future__ import annotations

"""
目标：演示 @tool 定义 + bind_tools + ToolNode 的基本用法
关键 API：@tool, ChatModel.bind_tools, ToolNode
运行命令：python 01_tool_node_basics.py
预期现象：
  1. 打印工具 schema（JSON 格式）
  2. FakeLLM 返回带 tool_calls 的 AIMessage
  3. ToolNode 自动路由并执行对应工具，返回 ToolMessage
生产提醒：
  - 真实场景请替换 FakeListChatModel 为 ChatOpenAI / ChatAnthropic
  - @tool 的 docstring 会作为工具描述传给 LLM，务必写清楚
"""

import json
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
    # 生产环境应使用安全的表达式解析器，此处仅做演示
    return str(eval(expression))  # noqa: S307


tools = [search, calculator]


def main() -> None:
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

    # ── 4. ToolNode 自动路由执行 ─────────────────────────────
    tool_node = ToolNode(tools)
    # ToolNode 接收 MessagesState，自动根据最后一条 AIMessage 的 tool_calls 执行
    result = tool_node.invoke({"messages": [fake_ai_message]})

    print("\n=== ToolNode 执行结果 ===")
    for msg in result["messages"]:
        assert isinstance(msg, ToolMessage)
        print(f"  工具: {msg.name} | 结果: {msg.content}")

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
    output = app.invoke({"messages": []})
    for msg in output["messages"]:
        print(f"  [{type(msg).__name__}] {msg.content or msg.tool_calls}")


if __name__ == "__main__":
    main()
