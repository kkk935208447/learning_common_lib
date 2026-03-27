"""
05_checkpointing / 02_conversation_threads

目标:
    演示多线程对话——不同 thread_id 维护独立的对话状态

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    MessagesState + MemorySaver, thread_id 命名约定

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/02_conversation_threads.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/05_checkpointing/02_conversation_threads.py

预期现象:
    1. 模拟两个用户各自的对话线程
    2. 每个线程独立维护消息历史
    3. 展示 thread_id 命名约定（参考 AgenticRAG: tenant:{id}:task:{id}）

生产提醒:
    - thread_id 命名建议：tenant:{tenant_id}:user:{user_id}:session:{session_id}
    - 长对话需要考虑消息裁剪策略，避免 context window 溢出
    - 可通过 get_state 检查任意线程的当前状态
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph


def assistant(state: MessagesState) -> dict:
    """简单助手：根据消息历史生成回复"""
    messages = state["messages"]
    last_user_msg = messages[-1].content if messages else ""

    # 模拟根据历史上下文回复
    history_summary = f"（历史消息 {len(messages) - 1} 条）"
    return {
        "messages": [
            AIMessage(content=f"{history_summary} 关于「{last_user_msg}」的回复")
        ]
    }


async def main() -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("assistant", assistant)
    graph.set_entry_point("assistant")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    # ── 1. thread_id 命名约定 ────────────────────────────────
    # 参考 AgenticRAG 的命名方式：tenant:{id}:task:{id}
    user_a_thread = {"configurable": {"thread_id": "tenant:acme:user:alice:session:001"}}
    user_b_thread = {"configurable": {"thread_id": "tenant:acme:user:bob:session:001"}}

    print("=== 用户 Alice 的对话 ===")
    conversations_a = ["你好，我想了解 LangGraph", "它和 LangChain 有什么区别？", "如何部署到生产环境？"]
    for msg in conversations_a:
        result = await app.ainvoke({"messages": [HumanMessage(content=msg)]}, config=user_a_thread)
        print(f"  Alice: {msg}")
        print(f"  Bot:   {result['messages'][-1].content}")

    print("\n=== 用户 Bob 的对话 ===")
    conversations_b = ["帮我写一个 Python 脚本", "加上错误处理"]
    for msg in conversations_b:
        result = await app.ainvoke({"messages": [HumanMessage(content=msg)]}, config=user_b_thread)
        print(f"  Bob:   {msg}")
        print(f"  Bot:   {result['messages'][-1].content}")

    # ── 2. 验证线程隔离 ─────────────────────────────────────
    print("\n=== 线程状态对比 ===")
    state_a = await app.aget_state(user_a_thread)
    state_b = await app.aget_state(user_b_thread)
    print(f"  Alice 线程消息数: {len(state_a.values['messages'])}")
    print(f"  Bob   线程消息数: {len(state_b.values['messages'])}")

    # ── 3. 列出所有消息（Alice 线程）────────────────────────
    print("\n=== Alice 完整对话历史 ===")
    for i, msg in enumerate(state_a.values["messages"]):
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        print(f"  {i}. [{role}] {msg.content}")


if __name__ == "__main__":
    asyncio.run(main())
