from __future__ import annotations

"""
目标：演示 astream_events(version="v2") 模式——细粒度事件流
关键 API：graph.astream_events(inputs, version="v2")
运行命令：python 03_stream_events.py
预期现象：
  1. 输出细粒度事件：on_chain_start/end, on_chat_model_stream, on_tool_start/end
  2. 每个事件包含 event, name, data 等字段
  3. 可以精确追踪每个节点和工具的执行过程
生产提醒：
  - 必须使用 version="v2"，v1 已废弃
  - 事件量大，生产环境应按 event 类型过滤
  - 适合构建详细的执行追踪 UI 或调试面板
  - 此文件使用异步 API，需要 asyncio 运行
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


@tool
def lookup_info(topic: str) -> str:
    """查询信息工具"""
    return f"关于 {topic} 的详细信息: 这是一个重要的技术概念"


tools = [lookup_info]


def fake_llm(state: MessagesState) -> dict:
    """模拟 LLM 节点"""
    messages = state["messages"]
    last = messages[-1]

    # 如果上一条是 ToolMessage，给出最终回答
    if hasattr(last, "tool_call_id"):
        return {"messages": [AIMessage(content=f"根据查询结果: {last.content}")]}

    # 否则请求调用工具
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_ev1", "name": "lookup_info", "args": {"topic": "LangGraph 事件流"}},
                ],
            )
        ]
    }


def should_continue(state: MessagesState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


async def main() -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("llm", fake_llm)
    graph.add_node("tools", ToolNode(tools))
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue)
    graph.add_edge("tools", "llm")

    app = graph.compile()

    # ── astream_events(version="v2") ────────────────────────
    print("=== astream_events(version='v2') ===\n")

    # 关注的事件类型
    interesting_events = {
        "on_chain_start",
        "on_chain_end",
        "on_tool_start",
        "on_tool_end",
        "on_chat_model_stream",
        "on_chat_model_start",
        "on_chat_model_end",
    }

    event_count = 0
    async for event in app.astream_events(
        {"messages": [HumanMessage(content="介绍 LangGraph 事件流")]},
        version="v2",
    ):
        event_type = event["event"]

        # 过滤只显示感兴趣的事件
        if event_type in interesting_events:
            event_count += 1
            name = event.get("name", "")
            # 提取关键数据
            data = event.get("data", {})
            data_summary = ""

            if event_type == "on_tool_start":
                inp = data.get("input", {})
                data_summary = f" input={inp}"
            elif event_type == "on_tool_end":
                output = data.get("output", "")
                if hasattr(output, "content"):
                    data_summary = f" output={output.content[:50]}"
            elif event_type in ("on_chain_start", "on_chain_end"):
                data_summary = ""

            print(f"  [{event_count:02d}] {event_type:<25} name={name:<20}{data_summary}")

    print(f"\n共捕获 {event_count} 个关键事件")

    # ── 按事件类型过滤示例 ──────────────────────────────────
    print("\n=== 仅过滤工具相关事件 ===")
    async for event in app.astream_events(
        {"messages": [HumanMessage(content="再次查询")]},
        version="v2",
    ):
        if event["event"] in ("on_tool_start", "on_tool_end"):
            print(f"  {event['event']}: {event.get('name', '')}")

    print("\n提示: 生产环境中按需过滤事件类型，避免处理过多无关事件")


if __name__ == "__main__":
    asyncio.run(main())
