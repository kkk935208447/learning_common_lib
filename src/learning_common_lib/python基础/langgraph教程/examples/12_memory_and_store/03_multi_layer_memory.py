"""
多层记忆系统设计。

目标:
    演示参考 AgenticRAG L1-L5 五层记忆架构的多层记忆系统设计，
    并将 L2/L3 的主线运行时切换为 Redis-first。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    - Graph State —— L1 工作记忆
    - Redis-first Checkpointer —— L2 短期记忆（checkpoint）
    - Redis-first Store —— L3 长期记忆（跨线程 KV）
    - 向量数据库接口 —— L4 外部记忆（知识库检索）
    - 聚合统计 —— L5 集体记忆（跨用户）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/12_memory_and_store/03_multi_layer_memory.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/12_memory_and_store/03_multi_layer_memory.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TypedDict

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


class MemoryState(TypedDict):
    user_id: str
    query: str
    l1_context: str
    l2_history: str
    l3_preferences: str
    l4_knowledge: str
    l5_trends: str
    response: str


MOCK_VECTOR_DB: dict[str, str] = {
    "LangGraph": "LangGraph 是构建有状态 AI 应用的框架，支持循环、分支和持久化。",
    "记忆系统": "多层记忆系统包括工作记忆、短期记忆、长期记忆等层次。",
}

MOCK_COLLECTIVE: dict[str, int] = {
    "LangGraph 教程": 156,
    "多 Agent 协作": 89,
    "记忆系统设计": 67,
}


def build_multi_layer_graph(store, checkpointer):
    def l1_working_memory(state: MemoryState) -> dict:
        context = f"用户 {state['user_id']} 询问: {state['query']}"
        print(f"[L1 工作记忆] {context}")
        return {"l1_context": context}

    def l2_short_term(state: MemoryState) -> dict:
        history = "（上轮对话摘要：用户对 LangGraph 感兴趣）"
        print(f"[L2 短期记忆] 恢复历史: {history}")
        return {"l2_history": history}

    def l3_long_term(state: MemoryState) -> dict:
        user_id = state["user_id"]
        namespace = DEFAULT_RUNTIME_SETTINGS.profile_namespace(user_id)
        items = store.search(namespace)

        if items:
            prefs = ", ".join(f"{item.key}={item.value}" for item in items)
        else:
            prefs = "暂无偏好记录"
            store.put(namespace, key="level", value={"v": "intermediate"})
            store.put(namespace, key="interest", value={"v": "AI框架"})

        print(f"[L3 长期记忆] 用户偏好: {prefs}")
        return {"l3_preferences": prefs}

    def l4_external(state: MemoryState) -> dict:
        query = state["query"]
        knowledge = "未找到相关知识"
        for keyword, doc in MOCK_VECTOR_DB.items():
            if keyword in query:
                knowledge = doc
                break
        print(f"[L4 外部记忆] 检索结果: {knowledge[:30]}...")
        return {"l4_knowledge": knowledge}

    def l5_collective(state: MemoryState) -> dict:
        top_topics = sorted(MOCK_COLLECTIVE.items(), key=lambda x: x[1], reverse=True)[:3]
        trends = ", ".join(f"{topic}({count}次)" for topic, count in top_topics)
        print(f"[L5 集体记忆] 热门趋势: {trends}")
        return {"l5_trends": trends}

    def synthesize(state: MemoryState) -> dict:
        response = (
            f"综合回复（基于五层记忆）:\n"
            f"  上下文: {state['l1_context']}\n"
            f"  历史: {state['l2_history']}\n"
            f"  偏好: {state['l3_preferences']}\n"
            f"  知识: {state['l4_knowledge'][:40]}...\n"
            f"  趋势: {state['l5_trends']}"
        )
        print("[synthesize] 综合五层记忆生成回复")
        return {"response": response}

    graph = StateGraph(MemoryState)
    graph.add_node("l1_working", l1_working_memory)
    graph.add_node("l2_short", l2_short_term)
    graph.add_node("l3_long", l3_long_term)
    graph.add_node("l4_external", l4_external)
    graph.add_node("l5_collective", l5_collective)
    graph.add_node("synthesize", synthesize)
    graph.set_entry_point("l1_working")
    graph.add_edge("l1_working", "l2_short")
    graph.add_edge("l2_short", "l3_long")
    graph.add_edge("l3_long", "l4_external")
    graph.add_edge("l4_external", "l5_collective")
    graph.add_edge("l5_collective", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile(checkpointer=checkpointer, store=store)


if __name__ == "__main__":
    async def main() -> None:
        checkpoint_mgr = CheckpointManager()
        store_mgr = StoreManager()
        checkpointer = await checkpoint_mgr.get_checkpointer()
        store = await store_mgr.get_store()
        app = build_multi_layer_graph(store, checkpointer)
        user_id = DEFAULT_RUNTIME_SETTINGS.demo_user_id("memory-user")
        thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("memory")

        print(
            f"store backend={store.backend}, degraded={store.degraded} | "
            f"checkpoint_backend={checkpoint_mgr.backend}, checkpoint_degraded={checkpoint_mgr.degraded} "
            f"store_last_error={store.last_error}"
        )
        print("=== 五层记忆系统演示 ===\n")
        print(f"user_id: {user_id}")
        print(f"thread_id: {thread_id}")

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }
        result = await app.ainvoke(
            {
                "user_id": user_id,
                "query": "LangGraph 的记忆系统怎么设计？",
                "l1_context": "",
                "l2_history": "",
                "l3_preferences": "",
                "l4_knowledge": "",
                "l5_trends": "",
                "response": "",
            },
            config=config,
        )

        print(f"\n{result['response']}")
        await checkpoint_mgr.aclose()
        await store_mgr.aclose()

    asyncio.run(main())
