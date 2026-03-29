"""
07_subgraph_composition / 05_command_parent_handoff

目标:
    演示子图通过 `Command(graph=Command.PARENT, ...)` 把控制权交回父图。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Command.PARENT、subgraph as node

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/07_subgraph_composition/05_command_parent_handoff.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/07_subgraph_composition/05_command_parent_handoff.py

预期现象:
    1. 父图把任务交给子图
    2. 子图检测到需要人工复核时，不在子图内继续兜圈子
    3. 子图直接把控制权交还父图，由父图进入 manual_review

生产提醒:
    - 子图适合解决局部闭环，父图负责全局推进决策
    - `Command.PARENT` 常用于 escalation / handoff / parent-only control flow
    - 本例故意保持两层图，避免把控制权回收机制和业务逻辑混在一起
"""
from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


class ParentState(TypedDict, total=False):
    query: str
    review_needed: bool
    subgraph_result: str
    final_result: str


class ChildState(TypedDict, total=False):
    query: str
    local_assessment: str
    review_needed: bool
    subgraph_result: str


def child_analyze(state: ChildState) -> dict:
    query = state.get("query", "")
    review_needed = "人工" in query or "高风险" in query
    assessment = "需要人工复核" if review_needed else "子图可自行完成"
    print(f"[child.analyze] query={query}")
    print(f"[child.analyze] local_assessment={assessment}")
    return {
        "local_assessment": assessment,
        "review_needed": review_needed,
    }


def child_route(state: ChildState):
    if state.get("review_needed"):
        print("[child.route] 通过 Command.PARENT 把控制权交回父图")
        return Command(
            graph=Command.PARENT,
            goto="manual_review",
            update={
                "review_needed": True,
                "subgraph_result": state.get("local_assessment", ""),
            },
        )
    return Command(goto="finish_local")


def child_finish_local(state: ChildState) -> dict:
    result = f"子图已完成: {state.get('local_assessment', '')}"
    print(f"[child.finish_local] {result}")
    return {"subgraph_result": result}


def build_child_graph():
    graph = StateGraph(ChildState)
    graph.add_node("analyze", child_analyze)
    graph.add_node("route", child_route)
    graph.add_node("finish_local", child_finish_local)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "route")
    graph.add_edge("finish_local", END)
    return graph.compile()


def parent_dispatch(state: ParentState) -> dict:
    print(f"[parent.dispatch] 把 query 交给子图: {state.get('query', '')}")
    return {}


def parent_manual_review(state: ParentState) -> dict:
    result = (
        "父图接管："
        f"review_needed={state.get('review_needed')} "
        f"subgraph_result={state.get('subgraph_result')}"
    )
    print(f"[parent.manual_review] {result}")
    return {"final_result": result}


def parent_finalize(state: ParentState) -> dict:
    result = state.get("subgraph_result", "无结果")
    print(f"[parent.finalize] {result}")
    return {"final_result": result}


def route_after_child(state: ParentState) -> Literal["manual_review", "finalize"]:
    return "manual_review" if state.get("review_needed") else "finalize"


async def main() -> None:
    child_graph = build_child_graph()
    parent = StateGraph(ParentState)
    parent.add_node("dispatch", parent_dispatch)
    parent.add_node("child_graph", child_graph)
    parent.add_node("manual_review", parent_manual_review)
    parent.add_node("finalize", parent_finalize)
    parent.add_edge(START, "dispatch")
    parent.add_edge("dispatch", "child_graph")
    parent.add_conditional_edges("child_graph", route_after_child)
    parent.add_edge("manual_review", END)
    parent.add_edge("finalize", END)
    app = parent.compile()

    # 图导出
    get_langgraph_png(app, "05_command_parent_handoff.png")

    print("=== 场景 1：子图自行完成 ===")
    completed = await app.ainvoke({"query": "普通知识检索请求"})
    print(f"final_result={completed['final_result']}\n")

    print("=== 场景 2：子图交回父图 ===")
    handoff = await app.ainvoke({"query": "高风险变更，需要人工审批"})
    print(f"final_result={handoff['final_result']}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    """导出父图 PNG。

    说明：xray=True 会把子图交给 langgraph.pregel._draw.draw_graph 做「节点替换」，
    但替换条件要求子图 Graph 同时满足 first_node() 与 last_node() 非空（用于对齐父图
    连入/连出边）。子图里若大量依赖 Command 动态跳转、静态分析画出的边不形成单一入口/
    唯一出口链，则 first/last 会为 None，合并被跳过，父图里子图仍显示为单个节点。

    需要单独看子图结构时：可对 build_child_graph().compile() 再 get_graph().draw_mermaid_png(...)。
    """
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
