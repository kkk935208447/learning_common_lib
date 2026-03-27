"""
Redis-first Store 实现跨线程长期记忆。

目标:
    演示使用 Redis-first Store 实现跨线程的长期记忆存储，
    不同对话线程可以共享用户偏好、历史摘要等持久化信息。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    - RedisStore / InMemoryStore —— 长期记忆后端
    - store.put(namespace, key, value) —— 写入
    - store.get(namespace, key) —— 读取
    - store.search(namespace_prefix) —— 搜索

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/12_memory_and_store/02_long_term_store.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/12_memory_and_store/02_long_term_store.py

预期现象:
    1. 优先尝试 Redis store
    2. 线程 A 中保存用户偏好
    3. 线程 B 中读取之前保存的偏好

生产提醒:
    - 生产环境优先使用 RedisStore，初始化失败时再降级为 InMemoryStore
    - namespace 设计要考虑多租户隔离
    - Store 适合结构化长期记忆，大文本建议存外部系统
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, StateGraph

try:
    from ...templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        StoreManager,
    )
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        StoreManager,
    )


class State(TypedDict):
    query: str
    response: str
    user_id: str


def build_store_graph(store, checkpointer):
    def load_preferences(state: State) -> dict:
        user_id = state["user_id"]
        namespace = DEFAULT_RUNTIME_SETTINGS.preference_namespace(user_id)
        items = store.search(namespace)

        if items:
            prefs = {item.key: item.value for item in items}
            print(f"[load] 用户 {user_id} 的偏好: {prefs}")
        else:
            print(f"[load] 用户 {user_id} 暂无偏好记录")
        return {}

    def process_and_learn(state: State) -> dict:
        user_id = state["user_id"]
        query = state["query"]
        namespace = DEFAULT_RUNTIME_SETTINGS.preference_namespace(user_id)

        if "喜欢" in query:
            preference = query.split("喜欢")[-1].strip()
            store.put(namespace, key="favorite_topic", value={"topic": preference})
            print(f"[learn] 记住用户偏好: favorite_topic = {preference}")

        if "用" in query and "语言" in query:
            lang = query.split("用")[-1].split("语言")[0].strip()
            store.put(namespace, key="language", value={"lang": lang})
            print(f"[learn] 记住编程语言偏好: {lang}")

        llm = FakeListChatModel(responses=["好的，我已经记住了你的偏好！"])
        result = llm.invoke(query)
        return {"response": result.content}

    graph = StateGraph(State)
    graph.add_node("load_preferences", load_preferences)
    graph.add_node("process_and_learn", process_and_learn)
    graph.set_entry_point("load_preferences")
    graph.add_edge("load_preferences", "process_and_learn")
    graph.add_edge("process_and_learn", END)
    return graph.compile(checkpointer=checkpointer, store=store)


if __name__ == "__main__":
    async def main() -> None:
        checkpoint_mgr = CheckpointManager()
        store_mgr = StoreManager()
        checkpointer = await checkpoint_mgr.get_checkpointer()
        store = await store_mgr.get_store()
        app = build_store_graph(store, checkpointer)
        user_id = DEFAULT_RUNTIME_SETTINGS.demo_user_id("store-user")
        thread_a = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("store-a")
        thread_b = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("store-b")

        print(
            f"Store backend: {store.backend}, degraded={store.degraded} | "
            f"checkpoint_backend={checkpoint_mgr.backend}, checkpoint_degraded={checkpoint_mgr.degraded} "
            f"store_last_error={store.last_error}"
        )
        print(f"user_id: {user_id}")
        print(f"thread_a: {thread_a}")
        print(f"thread_b: {thread_b}")

        print("=== 线程 A: 用户表达偏好 ===\n")
        config_a = {"configurable": {"thread_id": thread_a}}
        await app.ainvoke(
            {"query": "我喜欢机器学习", "response": "", "user_id": user_id},
            config=config_a,
        )

        print("\n=== 线程 B: 跨线程读取偏好 ===\n")
        config_b = {"configurable": {"thread_id": thread_b}}
        result = await app.ainvoke(
            {"query": "给我推荐一些内容", "response": "", "user_id": user_id},
            config=config_b,
        )
        print(f"\n回复: {result['response']}")

        print("\n=== Store 内容检查 ===")
        items = store.search(DEFAULT_RUNTIME_SETTINGS.preference_namespace(user_id))
        for item in items:
            print(f"  {item.key}: {item.value}")

        await checkpoint_mgr.aclose()
        await store_mgr.aclose()

    asyncio.run(main())
