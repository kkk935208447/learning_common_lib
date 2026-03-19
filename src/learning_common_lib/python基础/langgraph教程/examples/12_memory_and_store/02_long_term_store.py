"""Store 实现跨线程长期记忆

目标：
    演示使用 InMemoryStore 实现跨线程的长期记忆存储，
    不同对话线程可以共享用户偏好、历史摘要等持久化信息。

关键 API：
    - InMemoryStore —— 内存 KV 存储（开发用）
    - store.put(namespace, key, value) —— 写入
    - store.get(namespace, key) —— 读取
    - store.search(namespace) —— 搜索

运行命令：
    python 02_long_term_store.py

预期现象：
    线程 A 中保存用户偏好，线程 B 中能读取到该偏好（跨线程共享）。

生产提醒：
    - InMemoryStore 重启后数据丢失，生产环境使用持久化 Store 实现
    - namespace 设计要考虑多租户隔离：("users", user_id, "preferences")
    - Store 适合存储结构化元数据，大文本建议存向量数据库
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore


# ── 状态定义 ──────────────────────────────────────────────
class State(TypedDict):
    query: str
    response: str
    user_id: str


# ── 全局 Store 实例 ──────────────────────────────────────
store = InMemoryStore()


# ── 节点函数 ──────────────────────────────────────────────
def load_preferences(state: State) -> dict:
    """从 Store 加载用户长期偏好"""
    user_id = state["user_id"]
    namespace = ("users", user_id, "preferences")

    # 搜索该用户的所有偏好
    items = store.search(namespace)
    if items:
        prefs = {item.key: item.value for item in items}
        print(f"[load] 用户 {user_id} 的偏好: {prefs}")
    else:
        print(f"[load] 用户 {user_id} 暂无偏好记录")
    return {}


def process_and_learn(state: State) -> dict:
    """处理查询并学习用户偏好"""
    user_id = state["user_id"]
    query = state["query"]
    namespace = ("users", user_id, "preferences")

    # 模拟从对话中提取偏好
    if "喜欢" in query:
        # 提取偏好并存入 Store
        preference = query.split("喜欢")[-1].strip()
        store.put(namespace, key="favorite_topic", value={"topic": preference})
        print(f"[learn] 记住用户偏好: favorite_topic = {preference}")

    if "用" in query and "语言" in query:
        lang = query.split("用")[-1].split("语言")[0].strip()
        store.put(namespace, key="language", value={"lang": lang})
        print(f"[learn] 记住编程语言偏好: {lang}")

    # 使用 FakeListChatModel 模拟回复
    # 生产环境替换为: ChatOpenAI(model="gpt-4o")
    llm = FakeListChatModel(responses=["好的，我已经记住了你的偏好！"])
    result = llm.invoke(query)
    return {"response": result.content}


# ── 构建图 ──────────────────────────────────────────────
def build_store_graph():
    graph = StateGraph(State)
    graph.add_node("load_preferences", load_preferences)
    graph.add_node("process_and_learn", process_and_learn)
    graph.set_entry_point("load_preferences")
    graph.add_edge("load_preferences", "process_and_learn")
    graph.add_edge("process_and_learn", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, store=store)


if __name__ == "__main__":
    async def main() -> None:
        app = build_store_graph()

        print("=== 线程 A: 用户表达偏好 ===\n")
        config_a = {"configurable": {"thread_id": "thread-A"}}
        await app.ainvoke(
            {"query": "我喜欢机器学习", "response": "", "user_id": "user-42"},
            config=config_a,
        )

        print("\n=== 线程 B: 跨线程读取偏好 ===\n")
        config_b = {"configurable": {"thread_id": "thread-B"}}
        result = await app.ainvoke(
            {"query": "给我推荐一些内容", "response": "", "user_id": "user-42"},
            config=config_b,
        )
        print(f"\n回复: {result['response']}")

        print("\n=== Store 内容检查 ===")
        items = store.search(("users", "user-42", "preferences"))
        for item in items:
            print(f"  {item.key}: {item.value}")

    asyncio.run(main())
