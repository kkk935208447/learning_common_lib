from __future__ import annotations

import asyncio

"""
目标：演示 stream(mode="values") 模式——每步输出完整状态快照
关键 API：graph.stream(inputs, mode="values")
运行命令：python 01_stream_values.py
预期现象：
  1. 每个节点执行后输出当前完整状态
  2. 可以看到消息列表逐步增长
  3. 适用于需要完整状态的 UI 场景
生产提醒：
  - values 模式每步传输完整状态，消息多时数据量大
  - 适合需要渲染完整对话历史的前端
  - 如果只关心增量变化，使用 updates 模式更高效
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, StateGraph


def node_a(state: MessagesState) -> dict:
    """节点 A：初步处理"""
    return {"messages": [AIMessage(content="[节点A] 已接收并处理用户消息")]}


def node_b(state: MessagesState) -> dict:
    """节点 B：进一步处理"""
    return {"messages": [AIMessage(content="[节点B] 补充分析完成")]}


def node_c(state: MessagesState) -> dict:
    """节点 C：最终回复"""
    msg_count = len(state["messages"])
    return {"messages": [AIMessage(content=f"[节点C] 最终回复，共处理 {msg_count} 条消息")]}


async def main() -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_node("c", node_c)
    graph.set_entry_point("a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", END)

    app = graph.compile()

    # ── stream(mode="values")：每步完整状态快照 ─────────────
    print("=== stream(mode='values') ===")
    print("每步输出完整的 messages 列表:\n")

    step = 0
    async for state_snapshot in app.astream(
        {"messages": [HumanMessage(content="你好，请帮我分析一下")]},
        stream_mode="values",
    ):
        step += 1
        messages = state_snapshot["messages"]
        print(f"--- 步骤 {step} (共 {len(messages)} 条消息) ---")
        for msg in messages:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            print(f"  [{role}] {msg.content}")
        print()

    print(f"总共 {step} 个状态快照")
    print("\n提示: values 模式适合需要完整状态的 UI，如聊天界面渲染")


if __name__ == "__main__":
    asyncio.run(main())
