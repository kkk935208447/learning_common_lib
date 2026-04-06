"""
12_memory_and_store / 04_state_vs_store_boundary

目标:
    演示 state 和 store 的边界。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    InMemoryStore、state 只保留引用

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/12_memory_and_store/04_state_vs_store_boundary.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/12_memory_and_store/04_state_vs_store_boundary.py

预期现象:
    1. 把大文本直接放 state 会很臃肿
    2. 正确做法是把大对象放 store，只把 ref 放进 state

生产提醒:
    - checkpoint 恢复的是 state，不是对象仓库
    - state 越小，恢复越稳定
"""
from __future__ import annotations

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

    def bad_node(_: BoundaryState) -> dict:  # 参数写成 _ 既符合「必须接收 state」的节点签名，又清楚表达「本节点不依赖当前 state」
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
    print(f"  bad_state_shape={{'bad_payload_size': {result['bad_payload_size']}}}")
    print(
        "  good_state_shape="
        f"{{'document_ref': {result['document_ref']!r}, 'preview': {result['preview']!r}}}"
    )
    print(f"  bad_payload_size={result['bad_payload_size']}")
    print(f"  good_payload_size={result['good_payload_size']}")
    stored = store.get(("docs", "travel", "active"), "policy-001")
    print(f"  store_snapshot={stored.value if stored else None}")


if __name__ == "__main__":
    asyncio.run(main())
