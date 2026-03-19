"""Graph State 作为短期记忆（线程内）

目标：
    演示使用 MessagesState + checkpointer 实现线程内短期记忆，
    包括消息窗口管理和摘要压缩策略。

关键 API：
    - MessagesState —— 内置消息列表状态
    - MemorySaver —— 内存 checkpointer（线程内持久化）
    - trim_messages / summarize —— 窗口管理

运行命令：
    python 01_short_term_memory.py

预期现象：
    多轮对话中，图能记住之前的消息内容（同一 thread_id）。
    切换 thread_id 后记忆清空。演示消息窗口裁剪。

生产提醒：
    - MemorySaver 仅适合开发调试，生产环境使用 PostgresSaver / RedisSaver
    - 消息列表无限增长会导致 token 超限，务必实现窗口管理
    - 摘要压缩可以在保留语义的同时大幅减少 token 消耗
"""
from __future__ import annotations

from langchain_community.chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph


# ── 消息窗口管理工具 ──────────────────────────────────────
def trim_messages(messages: list, max_messages: int = 6) -> list:
    """保留最近 N 条消息 + 系统消息

    策略：始终保留 SystemMessage，对 Human/AI 消息做滑动窗口裁剪。
    生产环境可改为按 token 数裁剪。
    """
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]
    # 保留最近 max_messages 条非系统消息
    trimmed = system_msgs + other_msgs[-max_messages:]
    if len(other_msgs) > max_messages:
        print(f"  [trim] 裁剪消息: {len(other_msgs)} -> {max_messages}")
    return trimmed


# ── 节点函数 ──────────────────────────────────────────────
def chatbot_node(state: MessagesState) -> dict:
    """聊天节点：裁剪消息窗口后调用 LLM"""
    messages = trim_messages(state["messages"], max_messages=6)

    # 使用 FakeListChatModel 模拟 LLM
    # 生产环境替换为: ChatOpenAI(model="gpt-4o")
    fake_responses = [
        "我记得你之前说的内容！这是基于短期记忆的回复。",
    ]
    llm = FakeListChatModel(responses=fake_responses)
    response = llm.invoke(messages)

    return {"messages": [response]}


# ── 构建图 ──────────────────────────────────────────────
def build_memory_graph():
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", chatbot_node)
    graph.set_entry_point("chatbot")
    graph.add_edge("chatbot", END)

    # MemorySaver 提供线程内 checkpoint 持久化
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    app = build_memory_graph()

    # ── 同一线程多轮对话（短期记忆生效）──
    thread_config = {"configurable": {"thread_id": "user-001"}}

    print("=== 线程 user-001: 多轮对话 ===\n")

    conversations = [
        "你好，我叫小明",
        "我喜欢 Python 编程",
        "你还记得我叫什么吗？",
    ]

    for i, msg in enumerate(conversations, 1):
        print(f"[轮次 {i}] 用户: {msg}")
        result = app.invoke(
            {"messages": [HumanMessage(content=msg)]},
            config=thread_config,
        )
        ai_msg = result["messages"][-1]
        print(f"[轮次 {i}] AI: {ai_msg.content}\n")

    # ── 查看 checkpoint 中的消息数量 ──
    state = app.get_state(thread_config)
    print(f"线程 user-001 中的消息数: {len(state.values['messages'])}")

    # ── 切换线程（记忆隔离）──
    print("\n=== 线程 user-002: 新对话（无记忆）===\n")
    thread_config_2 = {"configurable": {"thread_id": "user-002"}}
    result2 = app.invoke(
        {"messages": [HumanMessage(content="你知道我是谁吗？")]},
        config=thread_config_2,
    )
    print(f"AI: {result2['messages'][-1].content}")
    state2 = app.get_state(thread_config_2)
    print(f"线程 user-002 中的消息数: {len(state2.values['messages'])}")
