from __future__ import annotations

"""
目标：演示工具执行失败时的处理策略——错误消息回传、LLM 自我纠正与安全退出
关键 API：ToolNode(handle_tool_errors=True), ToolException
运行命令：python 03_tool_error_handling.py
预期现象：
  1. 工具首次调用抛出异常
  2. ToolNode 在图内捕获异常并将错误信息作为 ToolMessage 回传
  3. LLM 根据错误信息自我纠正，发起第二次调用
  4. 第二次调用成功，Agent 循环正常结束
生产提醒：
  - handle_tool_errors=True 会将异常信息暴露给 LLM，注意不要泄露敏感堆栈
  - 可传入自定义函数 handle_tool_errors=my_handler 来格式化错误消息
  - 建议设置最大重试次数，防止无限循环
"""

import asyncio
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


# ── 1. 定义一个会失败的工具 ──────────────────────────────────
call_counter: dict[str, int] = {}


@tool
def unreliable_api(query: str) -> str:
    """不稳定的外部 API：第一次调用会失败，第二次成功"""
    call_counter.setdefault(query, 0)
    call_counter[query] += 1

    if call_counter[query] == 1:
        # 第一次调用：模拟失败
        raise ToolException(
            f"API 暂时不可用 (query='{query}')，请检查参数后重试。"
        )
    # 第二次调用：成功
    return f"查询 '{query}' 的结果: LangGraph 支持工具错误自动处理"


tools = [unreliable_api]


async def main() -> None:
    # ── 2. 完整 Agent 循环：ToolNode 回传错误，LLM 自我纠正 ──
    print("\n=== 完整 Agent 自我纠正循环 ===")
    call_counter.clear()  # 重置计数器
    round_count = 0
    max_rounds = 3  # 安全阀：防止无限循环

    def fake_llm_node(state: MessagesState) -> dict:
        nonlocal round_count
        round_count += 1

        if round_count > max_rounds:
            return {"messages": [AIMessage(content="抱歉，多次重试后仍然失败。")]}

        last = state["messages"][-1]

        # 如果上一条是错误的 ToolMessage，LLM "理解"错误并重试
        if isinstance(last, ToolMessage) and last.status == "error":
            print(f"  [LLM 第{round_count}轮] 收到错误，尝试重新调用...")
            return {
                "messages": [
                    AIMessage(
                        content="收到错误，我来重试一下",
                        tool_calls=[
                            {"id": f"call_retry_{round_count}", "name": "unreliable_api",
                             "args": {"query": "langgraph"}},
                        ],
                    )
                ]
            }

        # 如果上一条是成功的 ToolMessage，给出最终回答
        if isinstance(last, ToolMessage):
            print(f"  [LLM 第{round_count}轮] 工具成功，生成最终回答")
            return {"messages": [AIMessage(content=f"根据查询结果: {last.content}")]}

        # 首次调用：发起工具请求
        print(f"  [LLM 第{round_count}轮] 首次调用工具")
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "call_first", "name": "unreliable_api",
                         "args": {"query": "langgraph"}},
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
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue)
    graph.add_edge("tools", "llm")

    app = graph.compile()
    result = await app.ainvoke({"messages": [HumanMessage(content="查询 langgraph 信息")]})

    tool_messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
    error_messages = [msg for msg in tool_messages if msg.status == "error"]

    print(f"\n错误 ToolMessage 数量: {len(error_messages)}")
    if error_messages:
        first_error = error_messages[0]
        print(f"首个错误回传: status={first_error.status} content={first_error.content}")

    print("\n=== 消息流 ===")
    for msg in result["messages"]:
        role = type(msg).__name__
        status = getattr(msg, "status", "")
        status_str = f" (status={status})" if status else ""
        print(f"  [{role}{status_str}] {msg.content[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
