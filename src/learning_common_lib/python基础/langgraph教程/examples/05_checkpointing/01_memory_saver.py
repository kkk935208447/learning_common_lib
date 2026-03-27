"""
05_checkpointing / 01_memory_saver

目标:
    演示 MemorySaver 内存 checkpointer 的基本用法和 thread_id 隔离

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    MemorySaver, config={"configurable": {"thread_id": ...}}

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/01_memory_saver.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/05_checkpointing/01_memory_saver.py

预期现象:
    1. 同一 thread_id 下多次调用，状态自动累积
    2. 不同 thread_id 之间状态完全隔离
    3. 每个 superstep 自动保存 checkpoint

生产提醒:
    - MemorySaver 仅存储在内存中，进程重启后数据丢失
    - 生产环境应使用 AsyncRedisSaver 等持久化方案
    - thread_id 是字符串，建议使用有意义的命名（如 user:123:session:456）
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph


def chatbot(state: MessagesState) -> dict:
    """简单聊天节点：回显消息数量"""
    msg_count = len(state["messages"])
    return {
        "messages": [
            AIMessage(content=f"收到！当前对话共 {msg_count} 条消息（含本条回复共 {msg_count + 1} 条）")
        ]
    }


async def main() -> None:
    # ── 1. 创建带 MemorySaver 的图 ──────────────────────────
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", chatbot)
    graph.set_entry_point("chatbot")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    # ── 2. 同一 thread_id 下多轮对话 ────────────────────────
    thread_config = {"configurable": {"thread_id": "thread-001"}}

    print("=== 同一线程多轮对话 ===")
    r1 = await app.ainvoke({"messages": [HumanMessage(content="你好")]}, config=thread_config)
    print(f"  第1轮: {r1['messages'][-1].content}")

    r2 = await app.ainvoke({"messages": [HumanMessage(content="今天天气如何？")]}, config=thread_config)
    print(f"  第2轮: {r2['messages'][-1].content}")
    print(f"  消息总数: {len(r2['messages'])}")

    # ── 3. 不同 thread_id 状态隔离 ──────────────────────────
    other_config = {"configurable": {"thread_id": "thread-002"}}

    print("\n=== 不同线程状态隔离 ===")
    r3 = await app.ainvoke({"messages": [HumanMessage(content="新对话")]}, config=other_config)
    print(f"  thread-002 第1轮: {r3['messages'][-1].content}")
    print(f"  thread-002 消息数: {len(r3['messages'])}")

    # 验证 thread-001 不受影响
    state_001 = await app.aget_state(thread_config)
    print(f"  thread-001 消息数: {len(state_001.values['messages'])}（未受影响）")

    # ── 4. 查看 checkpoint 信息 ──────────────────────────────
    print("\n=== Checkpoint 信息 ===")
    state = await app.aget_state(thread_config)
    print(f"  checkpoint_id: {state.config['configurable'].get('checkpoint_id', 'N/A')}")
    print(f"  checkpoint_ns: {state.config['configurable'].get('checkpoint_ns', '')}")
    print(f"  消息数: {len(state.values['messages'])}")


if __name__ == "__main__":
    asyncio.run(main())
