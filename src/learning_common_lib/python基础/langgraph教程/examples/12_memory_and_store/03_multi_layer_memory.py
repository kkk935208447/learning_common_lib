"""多层记忆系统设计

目标：
    演示参考 AgenticRAG L1-L5 五层记忆架构的多层记忆系统设计，
    展示各层记忆的职责、存储方式和协作模式。

关键 API：
    - Graph State —— L1 工作记忆
    - MemorySaver —— L2 短期记忆（checkpoint）
    - InMemoryStore —— L3 长期记忆（跨线程 KV）
    - 向量数据库接口 —— L4 外部记忆（知识库检索）
    - 聚合统计 —— L5 集体记忆（跨用户）

运行命令：
    python 03_multi_layer_memory.py

预期现象：
    依次演示 L1-L5 各层记忆的读写操作，展示多层记忆协作流程。

生产提醒：
    - L1/L2 由 LangGraph 原生支持，L3 需要 Store，L4/L5 需要外部系统
    - 各层记忆的生命周期不同：L1 < L2 < L3 < L4 < L5
    - 生产环境建议实现记忆淘汰策略，避免存储无限增长
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore


# ══════════════════════════════════════════════════════════
# 五层记忆架构定义
# ══════════════════════════════════════════════════════════
#
# L1: 工作记忆 - Graph State（当前对话上下文）
#     生命周期: 单次图执行
#     存储位置: 内存中的 State 字典
#
# L2: 短期记忆 - Checkpoint（线程内持久化）
#     生命周期: 单个对话线程
#     存储位置: Checkpointer（MemorySaver / PostgresSaver）
#
# L3: 长期记忆 - Store（跨线程用户偏好）
#     生命周期: 用户级别，跨多个对话
#     存储位置: Store（InMemoryStore / 持久化 Store）
#
# L4: 外部记忆 - 向量数据库（知识库检索）
#     生命周期: 系统级别，持久化
#     存储位置: ChromaDB / Pinecone / Milvus
#
# L5: 集体记忆 - 跨用户聚合（热门问题、最佳实践）
#     生命周期: 全局级别，持续更新
#     存储位置: 数据库 + 缓存


# ── 状态定义（L1 工作记忆）──────────────────────────────
class MemoryState(TypedDict):
    """L1 工作记忆：当前执行上下文"""
    user_id: str
    query: str
    l1_context: str       # 工作记忆：当前上下文
    l2_history: str       # 短期记忆：对话历史摘要
    l3_preferences: str   # 长期记忆：用户偏好
    l4_knowledge: str     # 外部记忆：检索到的知识
    l5_trends: str        # 集体记忆：热门趋势
    response: str


# ── 模拟 L4 向量数据库 ──────────────────────────────────
MOCK_VECTOR_DB: dict[str, str] = {
    "LangGraph": "LangGraph 是构建有状态 AI 应用的框架，支持循环、分支和持久化。",
    "记忆系统": "多层记忆系统包括工作记忆、短期记忆、长期记忆等层次。",
}

# ── 模拟 L5 集体记忆 ──────────────────────────────────
MOCK_COLLECTIVE: dict[str, int] = {
    "LangGraph 教程": 156,
    "多 Agent 协作": 89,
    "记忆系统设计": 67,
}

# ── 全局 Store（L3）──────────────────────────────────────
store = InMemoryStore()


# ── 节点函数 ──────────────────────────────────────────────
def l1_working_memory(state: MemoryState) -> dict:
    """L1 工作记忆：构建当前执行上下文"""
    context = f"用户 {state['user_id']} 询问: {state['query']}"
    print(f"[L1 工作记忆] {context}")
    return {"l1_context": context}


def l2_short_term(state: MemoryState) -> dict:
    """L2 短期记忆：从 checkpoint 恢复对话历史

    实际由 checkpointer 自动管理，这里模拟读取逻辑。
    """
    # 在真实场景中，MessagesState + checkpointer 自动处理
    history = "（上轮对话摘要：用户对 LangGraph 感兴趣）"
    print(f"[L2 短期记忆] 恢复历史: {history}")
    return {"l2_history": history}


def l3_long_term(state: MemoryState) -> dict:
    """L3 长期记忆：从 Store 读取用户偏好"""
    user_id = state["user_id"]
    namespace = ("users", user_id, "profile")

    items = store.search(namespace)
    if items:
        prefs = ", ".join(f"{item.key}={item.value}" for item in items)
    else:
        prefs = "暂无偏好记录"
        # 首次访问，初始化偏好
        store.put(namespace, key="level", value={"v": "intermediate"})
        store.put(namespace, key="interest", value={"v": "AI框架"})

    print(f"[L3 长期记忆] 用户偏好: {prefs}")
    return {"l3_preferences": prefs}


def l4_external(state: MemoryState) -> dict:
    """L4 外部记忆：从向量数据库检索相关知识"""
    query = state["query"]
    # 模拟向量检索（生产环境替换为真实向量数据库调用）
    knowledge = "未找到相关知识"
    for keyword, doc in MOCK_VECTOR_DB.items():
        if keyword in query:
            knowledge = doc
            break
    print(f"[L4 外部记忆] 检索结果: {knowledge[:30]}...")
    return {"l4_knowledge": knowledge}


def l5_collective(state: MemoryState) -> dict:
    """L5 集体记忆：获取跨用户聚合趋势"""
    # 模拟获取热门话题
    top_topics = sorted(MOCK_COLLECTIVE.items(), key=lambda x: x[1], reverse=True)[:3]
    trends = ", ".join(f"{t[0]}({t[1]}次)" for t in top_topics)
    print(f"[L5 集体记忆] 热门趋势: {trends}")
    return {"l5_trends": trends}


def synthesize(state: MemoryState) -> dict:
    """综合所有层级的记忆生成最终回复"""
    response = (
        f"综合回复（基于五层记忆）:\n"
        f"  上下文: {state['l1_context']}\n"
        f"  历史: {state['l2_history']}\n"
        f"  偏好: {state['l3_preferences']}\n"
        f"  知识: {state['l4_knowledge'][:40]}...\n"
        f"  趋势: {state['l5_trends']}"
    )
    print(f"[synthesize] 综合五层记忆生成回复")
    return {"response": response}


# ── 构建图 ──────────────────────────────────────────────
def build_multi_layer_graph():
    graph = StateGraph(MemoryState)

    graph.add_node("l1_working", l1_working_memory)
    graph.add_node("l2_short", l2_short_term)
    graph.add_node("l3_long", l3_long_term)
    graph.add_node("l4_external", l4_external)
    graph.add_node("l5_collective", l5_collective)
    graph.add_node("synthesize", synthesize)

    # L1 -> L2 -> L3 -> L4 -> L5 -> synthesize
    # 生产环境中 L3/L4/L5 可以并行执行
    graph.set_entry_point("l1_working")
    graph.add_edge("l1_working", "l2_short")
    graph.add_edge("l2_short", "l3_long")
    graph.add_edge("l3_long", "l4_external")
    graph.add_edge("l4_external", "l5_collective")
    graph.add_edge("l5_collective", "synthesize")
    graph.add_edge("synthesize", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, store=store)


if __name__ == "__main__":
    app = build_multi_layer_graph()

    print("=== 五层记忆系统演示 ===\n")
    config = {"configurable": {"thread_id": "demo-thread"}}
    result = app.invoke(
        {
            "user_id": "user-42",
            "query": "LangGraph 的记忆系统怎么设计？",
            "l1_context": "", "l2_history": "", "l3_preferences": "",
            "l4_knowledge": "", "l5_trends": "", "response": "",
        },
        config=config,
    )

    print(f"\n{result['response']}")
