"""
TypedDict 定义状态 schema，默认覆盖语义。

目标:
    理解 TypedDict 作为 LangGraph 状态的基本用法

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph, TypedDict, total 参数

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/02_state_deep_dive/01_typed_dict_state.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/02_state_deep_dive/01_typed_dict_state.py

预期现象:
    演示 total=True（默认）与 total=False 的区别，以及 last-write-wins 覆盖行为

生产提醒:
    TypedDict 仅提供类型提示，运行时不做校验；需要运行时校验请用 Pydantic
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 状态定义 ----------
# total=True（默认）：所有字段都是必需的
class StrictState(TypedDict):
    name: str
    score: int


# total=False：所有字段都是可选的
class FlexibleState(TypedDict, total=False):
    name: str
    score: int
    tag: str  # 可选字段，节点可以不返回


# ---------- 节点函数 ----------
def init_node(state: StrictState) -> dict:
    """初始化节点：设置初始分数。"""
    print(f"[init] 收到: {state}")
    return {"score": 10}


def update_node(state: StrictState) -> dict:
    """更新节点：覆盖分数（last-write-wins）。"""
    # 无 reducer 时，返回的字段直接覆盖旧值
    new_score = state["score"] + 5
    print(f"[update] score: {state['score']} -> {new_score}")
    return {"score": new_score}


def flexible_node(state: FlexibleState) -> dict:
    """演示可选字段：安全地访问可能不存在的字段。"""
    tag = state.get("tag", "默认标签")
    print(f"[flexible] tag={tag}")
    return {"tag": tag + "_已处理"}


# ---------- 构建图 ----------
async def demo_strict() -> None:
    """演示 total=True 的严格状态。"""
    print("=== StrictState (total=True) ===")
    graph = StateGraph(StrictState)
    graph.add_node("init", init_node)
    graph.add_node("update", update_node)
    graph.add_edge(START, "init")
    graph.add_edge("init", "update")
    graph.add_edge("update", END)
    app = graph.compile()

    # 必须提供所有字段
    result = await app.ainvoke({"name": "测试用户", "score": 0})
    print(f"结果: {result}\n")


async def demo_flexible() -> None:
    """演示 total=False 的灵活状态。"""
    print("=== FlexibleState (total=False) ===")
    graph = StateGraph(FlexibleState)
    graph.add_node("flex", flexible_node)
    graph.add_edge(START, "flex")
    graph.add_edge("flex", END)
    app = graph.compile()

    # 可以只提供部分字段
    result = await app.ainvoke({"name": "用户A"})
    print(f"不传 tag: {result}")

    result = await app.ainvoke({"name": "用户B", "tag": "VIP"})
    print(f"传了 tag: {result}\n")


async def main() -> None:
    await demo_strict()
    await demo_flexible()

    # 演示 last-write-wins
    print("=== Last-Write-Wins 演示 ===")
    print("无 reducer 时，后写入的值直接覆盖先前的值")
    print("如果需要追加/累积语义，请使用 Annotated + reducer")


if __name__ == "__main__":
    asyncio.run(main())
