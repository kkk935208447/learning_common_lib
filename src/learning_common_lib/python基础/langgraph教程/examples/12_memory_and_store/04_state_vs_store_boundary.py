from __future__ import annotations

"""
目标：演示 state 和 store 的边界。
关键 API：InMemoryStore、state 只保留引用
运行命令：python 04_state_vs_store_boundary.py
预期现象：
  1. 把大文本直接放 state 会很臃肿
  2. 正确做法是把大对象放 store，只把 ref 放进 state
生产提醒：
  - checkpoint 恢复的是 state，不是对象仓库
  - state 越小，恢复越稳定
"""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore


class BoundaryState(TypedDict, total=False):
    document_ref: str
    preview: str
    bad_payload_size: int
    good_payload_size: int


BIG_TEXT = "差旅制度原文|" * 300


async def main() -> None:
    store = InMemoryStore()

    def bad_node(_: BoundaryState) -> dict:
        print(f"[bad] 直接把大文本塞进 state，字符数={len(BIG_TEXT)}")
        return {"bad_payload_size": len(BIG_TEXT)}

    def good_node(state: BoundaryState) -> dict:
        namespace = ("docs", "travel", "active")
        store.put(namespace, "policy-001", {"content": BIG_TEXT})
        document_ref = "store://docs/travel/active/policy-001"
        preview = BIG_TEXT[:20] + "..."
        print(f"[good] 大文本进 store，state 里只保留 ref={document_ref}")
        return {
            "document_ref": document_ref,
            "preview": preview,
            "good_payload_size": len(document_ref) + len(preview),
        }

    graph = StateGraph(BoundaryState)
    graph.add_node("bad", bad_node)
    graph.add_node("good", good_node)
    graph.add_edge(START, "bad")
    graph.add_edge("bad", "good")
    graph.add_edge("good", END)
    app = graph.compile(store=store)

    result = await app.ainvoke({})
    print("\n对比:")
    print(f"  bad_payload_size={result['bad_payload_size']}")
    print(f"  good_payload_size={result['good_payload_size']}")


if __name__ == "__main__":
    asyncio.run(main())
