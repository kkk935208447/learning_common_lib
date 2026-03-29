"""
07_subgraph_composition / 01_subgraph_as_node

目标:
    演示将编译后的子图作为父图节点使用

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    add_node("sub", compiled_subgraph)

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/07_subgraph_composition/01_subgraph_as_node.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/07_subgraph_composition/01_subgraph_as_node.py

预期现象:
    父图依次执行 pre → 子图(step1→step2) → post，打印完整执行链路

生产提醒:
    子图独立编译后拥有独立状态空间，父子图通过重叠 key 共享数据
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    # 默认 get_graph() 的 xray=False：嵌套的已编译子图在图中只显示为一个节点，不展开内部。xray=True 会递归收集子图并交给 draw_graph，导出的 PNG 才能看到 step1/step2 等内部结构。
    app.get_graph(xray=True).draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")

# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class SubState(TypedDict, total=False):
    """子图状态：只关心 items 列表"""
    items: Annotated[list[str], operator.add]


class ParentState(TypedDict, total=False):
    """父图状态：包含 items（与子图共享）和 summary"""
    items: Annotated[list[str], operator.add]
    summary: str


# ---------------------------------------------------------------------------
# 子图节点
# ---------------------------------------------------------------------------

def step1_fn(state: SubState) -> dict:
    """子图第一步：添加处理标记"""
    print("[子图] step1 执行")
    return {"items": ["sub_step1_done"]}


def step2_fn(state: SubState) -> dict:
    """子图第二步：添加完成标记"""
    print("[子图] step2 执行")
    return {"items": ["sub_step2_done"]}


# ---------------------------------------------------------------------------
# 构建并编译子图
# ---------------------------------------------------------------------------

sub_builder = StateGraph(SubState)
sub_builder.add_node("step1", step1_fn)
sub_builder.add_node("step2", step2_fn)
sub_builder.add_edge(START, "step1")
sub_builder.add_edge("step1", "step2")
sub_builder.add_edge("step2", END)
sub_graph = sub_builder.compile()  # 独立编译

# ---------------------------------------------------------------------------
# 父图节点
# ---------------------------------------------------------------------------

def pre_fn(state: ParentState) -> dict:
    """父图前置处理"""
    print("[父图] pre 执行")
    return {"items": ["pre_done"]}


def post_fn(state: ParentState) -> dict:
    """父图后置处理：汇总所有 items"""
    print("[父图] post 执行")
    all_items = state.get("items", [])
    return {"summary": f"共处理 {len(all_items)} 个步骤: {all_items}"}


# ---------------------------------------------------------------------------
# 构建父图，将子图作为节点
# ---------------------------------------------------------------------------

parent_builder = StateGraph(ParentState)
parent_builder.add_node("pre", pre_fn)
parent_builder.add_node("sub", sub_graph)  # 编译后的子图直接作为节点
parent_builder.add_node("post", post_fn)
parent_builder.add_edge(START, "pre")
parent_builder.add_edge("pre", "sub")
parent_builder.add_edge("sub", "post")
parent_builder.add_edge("post", END)

graph = parent_builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    get_langgraph_png(graph, "01_subgraph_as_node.png")    # 导出图

    result = graph.invoke({"items": []})
    print(f"\n最终状态: {result}")
    print(f"摘要: {result.get('summary', '')}")
