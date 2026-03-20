"""MessagesState 预置 schema 与 add_messages reducer。

目标：掌握 LangGraph 内置的 MessagesState 及 add_messages 的去重/更新逻辑
关键 API：MessagesState, add_messages, HumanMessage, AIMessage, SystemMessage
运行命令：python 03_message_state.py
预期现象：使用 FakeListChatModel 模拟对话，展示消息按 ID 去重/更新
生产提醒：生产环境替换 FakeListChatModel 为真实 LLM（如 ChatOpenAI）
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

# ---------- LLM 配置 ----------
# 使用 FakeListChatModel 模拟 LLM 响应，无需 API Key
# 生产环境替换为：
#   from langchain_openai import ChatOpenAI
#   llm = ChatOpenAI(model="gpt-4o-mini")
llm = FakeListChatModel(responses=[
    "你好！我是 AI 助手，有什么可以帮你的？",
    "LangGraph 是一个用于构建有状态多步骤 AI 应用的框架。",
    "再见！祝你编码愉快！",
])


# ---------- 节点函数 ----------
def chatbot(state: MessagesState) -> dict:
    """聊天节点：调用 LLM 生成回复。

    MessagesState 内置了 messages 字段，使用 add_messages reducer。
    add_messages 的内部逻辑：
    - 新消息直接追加到列表末尾
    - 如果新消息的 ID 与已有消息相同，则更新（而非追加）
    - 这使得消息修正/重试成为可能
    """
    response = llm.invoke(state["messages"])
    print(f"[chatbot] 生成回复: {response.content[:50]}...")
    return {"messages": [response]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", chatbot)
    graph.add_edge(START, "chatbot")
    graph.add_edge("chatbot", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    # 演示 1：基本对话
    print("=== 基本对话 ===")
    result = await app.ainvoke({"messages": [
        SystemMessage(content="你是一个友好的 AI 助手"),
        HumanMessage(content="你好！"),
    ]})
    for msg in result["messages"]:
        role = msg.__class__.__name__.replace("Message", "")
        print(f"  [{role}] {msg.content}")

    # 演示 2：消息类型说明
    print("\n=== 消息类型 ===")
    print("  HumanMessage  - 用户输入")
    print("  AIMessage     - AI 回复")
    print("  SystemMessage - 系统指令（通常放在最前面）")

    # 演示 3：add_messages 的 ID 去重机制
    print("\n=== add_messages ID 去重 ===")
    msg1 = HumanMessage(content="原始消息", id="msg-001")
    msg2 = HumanMessage(content="修改后的消息", id="msg-001")
    from langgraph.graph.message import add_messages
    merged = add_messages([msg1], [msg2])
    print(f"  合并前: ['{msg1.content}']")
    print(f"  合并后: ['{merged[-1].content}']  (同 ID 被更新)")


if __name__ == "__main__":
    asyncio.run(main())
