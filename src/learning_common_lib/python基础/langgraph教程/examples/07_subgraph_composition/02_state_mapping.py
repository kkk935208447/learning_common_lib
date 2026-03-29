"""
07_subgraph_composition / 02_state_mapping

目标:
    演示父子图状态 schema 不同时的映射机制

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    重叠 key 自动共享、非重叠 key 为子图私有状态

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/07_subgraph_composition/02_state_mapping.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/07_subgraph_composition/02_state_mapping.py

预期现象:
    子图通过重叠 key 'query' 接收父图数据，子图私有 key 'internal_score' 不会泄漏到父图

生产提醒:
    设计子图时明确哪些 key 需要与父图共享，哪些应保持私有
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
# 状态定义 — 父子图 schema 不同
# ---------------------------------------------------------------------------

class ParentState(TypedDict, total=False):
    """父图状态"""
    query: str                                        # 与子图共享
    results: Annotated[list[str], operator.add]       # 与子图共享
    final_answer: str                                 # 父图独有


class ChildState(TypedDict, total=False):
    """子图状态"""
    query: str                                        # 与父图共享（重叠 key）
    results: Annotated[list[str], operator.add]       # 与父图共享（重叠 key）
    internal_score: float                             # 子图私有（非重叠 key）


# ---------------------------------------------------------------------------
# 子图节点
# ---------------------------------------------------------------------------

def child_search(state: ChildState) -> dict:
    """子图搜索节点：使用 query 搜索并产生内部评分"""
    query = state.get("query", "")
    print(f"[子图] 搜索 query='{query}'")
    # 模拟搜索结果和内部评分
    return {
        "results": [f"搜索结果: '{query}' 的匹配项"],
        "internal_score": 0.95,  # 私有状态，不会传回父图
    }


def child_rank(state: ChildState) -> dict:
    """子图排序节点：基于内部评分排序"""
    score = state.get("internal_score", 0.0)
    print(f"[子图] 排序 internal_score={score}")
    return {"results": [f"排序完成(score={score})"]}


# ---------------------------------------------------------------------------
# 编译子图
# ---------------------------------------------------------------------------

child_builder = StateGraph(ChildState)
child_builder.add_node("search", child_search)
child_builder.add_node("rank", child_rank)
child_builder.add_edge(START, "search")
child_builder.add_edge("search", "rank")
child_builder.add_edge("rank", END)
child_graph = child_builder.compile()


# ---------------------------------------------------------------------------
# 父图节点
# ---------------------------------------------------------------------------

def prepare(state: ParentState) -> dict:
    """父图准备节点"""
    print(f"[父图] 准备查询: {state.get('query', '')}")
    return {}


def summarize(state: ParentState) -> dict:
    """父图汇总节点"""
    results = state.get("results", [])
    print(f"[父图] 汇总 {len(results)} 条结果")
    # 注意：这里访问不到子图的 internal_score
    return {"final_answer": f"基于 {len(results)} 条结果生成最终答案"}


# ---------------------------------------------------------------------------
# 构建父图
# ---------------------------------------------------------------------------

parent_builder = StateGraph(ParentState)
parent_builder.add_node("prepare", prepare)
parent_builder.add_node("child", child_graph)  # 子图作为节点
parent_builder.add_node("summarize", summarize)
parent_builder.add_edge(START, "prepare")
parent_builder.add_edge("prepare", "child")
parent_builder.add_edge("child", "summarize")
parent_builder.add_edge("summarize", END)

graph = parent_builder.compile()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    get_langgraph_png(graph, "02_state_mapping.png")    # 导出图

    result = graph.invoke({"query": "LangGraph 子图状态映射", "results": []})
    print(f"\n最终父图状态: {result}")
    # internal_score 不会出现在父图状态中
    print(f"父图是否包含 internal_score: {'internal_score' in result}")
