"""
Mermaid 可视化与 draw_mermaid_png 导出。

目标:
    学会将 LangGraph 图导出为可视化图表

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    get_graph(), draw_mermaid(), draw_mermaid_png(), draw_png()

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/01_graph_fundamentals/04_graph_visualization.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/01_graph_fundamentals/04_graph_visualization.py

预期现象:
    打印 Mermaid 文本，并尝试生成 PNG 图片文件

生产提醒:
    draw_mermaid_png 需要网络访问 mermaid.ink；draw_png 需要本地安装 graphviz
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 状态与节点 ----------
class State(TypedDict):
    data: str
    log: Annotated[list[str], operator.add]


def preprocess(state: State) -> dict:
    return {"data": state["data"].strip(), "log": ["preprocess"]}


def validate(state: State) -> dict:
    return {"log": ["validate"]}


def transform(state: State) -> dict:
    return {"data": state["data"].upper(), "log": ["transform"]}


def route_decision(state: State) -> str:
    """条件路由：数据长度决定走哪条路。"""
    return "transform" if len(state["data"]) > 3 else "end"


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("preprocess", preprocess)
    graph.add_node("validate", validate)
    graph.add_node("transform", transform)

    graph.add_edge(START, "preprocess")
    graph.add_edge("preprocess", "validate")
    # 条件边让可视化更有意义
    graph.add_conditional_edges(
        "validate",
        route_decision,
        {"transform": "transform", "end": END},
    )
    graph.add_edge("transform", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    # 1. 获取 Mermaid 文本
    mermaid_text: str = app.get_graph().draw_mermaid()
    print("=== Mermaid 图定义 ===")
    print(mermaid_text)

    # 2. 尝试生成 PNG（需要网络或 graphviz）
    try:
        png_bytes: bytes = app.get_graph().draw_mermaid_png()
        output_path = "graph_visualization.png"
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        print(f"\nPNG 已保存到 {output_path}")
    except Exception as e:
        print(f"\ndraw_mermaid_png 失败（可能需要网络）: {e}")

    # 3. 如果安装了 pygraphviz，也可以用 draw_png
    try:
        png_bytes_gv: bytes = app.get_graph().draw_png()
        with open("graph_visualization_graphviz.png", "wb") as f:
            f.write(png_bytes_gv)
        print("graphviz PNG 已保存")
    except Exception:
        print("draw_png 不可用（需要 pip install pygraphviz）")

    # 4. async-first 主线使用 ainvoke 执行图
    result = await app.ainvoke({"data": "  hello world  ", "log": []})
    print(f"\n执行结果: {result}")


if __name__ == "__main__":
    asyncio.run(main())
