from __future__ import annotations

"""
目标：演示 ToolNode 中的 InjectedStore / InjectedState。
关键 API：InjectedStore、InjectedState、ToolNode
运行命令：python 06_tool_with_injected_store.py
预期现象：
  1. 模型只生成普通工具参数
  2. store 和 user_id 由系统注入，不暴露给模型
  3. 工具可跨会话读取长期偏好
生产提醒：
  - 不要把整个 state 明文交给模型
  - tool 的系统注入参数应该对模型不可见
"""

import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import InjectedState, InjectedStore, ToolNode
from langgraph.store.memory import InMemoryStore


class PreferenceState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str


@tool
def save_preference(
    topic: str,
    store: Annotated[InMemoryStore, InjectedStore()],
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """保存用户偏好。"""
    namespace = ("users", user_id, "prefs")
    store.put(namespace, "favorite_topic", {"value": topic})
    return f"已保存 favorite_topic={topic}"


@tool
def read_preference(
    store: Annotated[InMemoryStore, InjectedStore()],
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """读取用户偏好。"""
    namespace = ("users", user_id, "prefs")
    item = store.get(namespace, "favorite_topic")
    if item is None:
        return "暂无偏好记录"
    return f"favorite_topic={item.value['value']}"


TOOLS = [save_preference, read_preference]


def agent(state: PreferenceState) -> dict:
    last = state["messages"][-1]
    if isinstance(last, HumanMessage):
        if "记住" in last.content:
            return {
                "messages": [
                    AIMessage(
                        content="我来记住你的偏好",
                        tool_calls=[
                            {
                                "id": "tool-save-1",
                                "name": "save_preference",
                                "args": {"topic": "Python"},
                            }
                        ],
                    )
                ]
            }
        return {
            "messages": [
                AIMessage(
                    content="我来读取你的偏好",
                    tool_calls=[
                        {
                            "id": "tool-read-1",
                            "name": "read_preference",
                            "args": {},
                        }
                    ],
                )
            ]
        }

    if isinstance(last, ToolMessage):
        return {"messages": [AIMessage(content=f"工具结果：{last.content}")]}
    return {"messages": [AIMessage(content="无需工具调用")]}


def should_continue(state: PreferenceState):
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "__end__"


async def main() -> None:
    store = InMemoryStore()
    graph = StateGraph(PreferenceState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.set_entry_point("agent")
    app = graph.compile(store=store)

    user_id = "user-tool-store"
    print("=== 第一轮：保存偏好 ===")
    saved = await app.ainvoke(
        {"messages": [HumanMessage(content="请记住我偏好 Python")], "user_id": user_id}
    )
    print(saved["messages"][-1].content)

    print("\n=== 第二轮：跨会话读取偏好 ===")
    loaded = await app.ainvoke(
        {"messages": [HumanMessage(content="我之前喜欢什么主题？")], "user_id": user_id}
    )
    print(loaded["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
