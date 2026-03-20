"""Annotated + reducer：追加语义与自定义归约。

目标：掌握 Annotated[type, reducer] 机制，实现追加、累加、去重等语义
关键 API：Annotated, operator.add, 自定义 reducer 函数
运行命令：python 02_annotated_reducers.py
预期现象：messages 列表追加而非覆盖，count 累加，unique_tags 自动去重
生产提醒：reducer 签名为 (left, right) -> merged，必须是纯函数且幂等
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 自定义 reducer 函数 ----------
def deduplicate_reducer(left: list[str], right: list[str]) -> list[str]:
    """去重 reducer：合并两个列表并去重，保持顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in left + right:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def capped_add(left: int, right: int) -> int:
    """带上限的累加 reducer：最大不超过 100。"""
    return min(left + right, 100)


# ---------- 状态定义 ----------
class State(TypedDict):
    # operator.add：列表追加语义
    messages: Annotated[list[str], operator.add]
    # lambda 自定义累加
    count: Annotated[int, lambda left, right: left + right]
    # 自定义去重 reducer
    unique_tags: Annotated[list[str], deduplicate_reducer]
    # 带上限的累加
    score: Annotated[int, capped_add]


# ---------- 节点函数 ----------
def node_a(state: State) -> dict:
    print(f"[节点A] messages={state['messages']}, count={state['count']}")
    return {
        "messages": ["来自节点A的消息"],
        "count": 1,
        "unique_tags": ["tag_a", "tag_common"],
        "score": 30,
    }


def node_b(state: State) -> dict:
    print(f"[节点B] messages={state['messages']}, count={state['count']}")
    return {
        "messages": ["来自节点B的消息"],
        "count": 1,
        "unique_tags": ["tag_b", "tag_common"],  # tag_common 会被去重
        "score": 50,
    }


def node_c(state: State) -> dict:
    print(f"[节点C] messages={state['messages']}, count={state['count']}")
    return {
        "messages": ["来自节点C的消息"],
        "count": 1,
        "unique_tags": ["tag_c"],
        "score": 30,  # 30+50+30=110 但 capped_add 限制为 100
    }


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_node("c", node_c)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", END)
    return graph


async def main() -> None:
    app = build_graph().compile()
    result = await app.ainvoke({
        "messages": ["初始消息"],
        "count": 0,
        "unique_tags": [],
        "score": 0,
    })

    print("\n=== 最终结果 ===")
    print(f"messages (追加): {result['messages']}")
    print(f"count (累加): {result['count']}")
    print(f"unique_tags (去重): {result['unique_tags']}")
    print(f"score (带上限累加): {result['score']}")


if __name__ == "__main__":
    asyncio.run(main())
