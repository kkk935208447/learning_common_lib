"""
最小两节点图 START → A → END。

目标:
    理解 LangGraph 最基本的图构建流程

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph, add_node, add_edge, compile, invoke

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/01_graph_fundamentals/01_minimal_graph.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/01_graph_fundamentals/01_minimal_graph.py

预期现象:
    打印 "开始 -> 经过节点A"，展示状态在节点间的传递

生产提醒:
    compile() 会冻结拓扑并校验边的合法性，编译后不可再修改图结构
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 状态定义 ----------
class State(TypedDict):
    message: str


# ---------- 节点函数 ----------
def node_a(state: State) -> dict:
    """节点 A：在消息后追加文本。

    节点函数接收当前完整状态，返回 *partial* 字典，
    LangGraph 会自动合并到状态中（无 reducer 时为 last-write-wins）。
    """
    print(f"[节点A] 收到状态: {state}")
    return {"message": state["message"] + " -> 经过节点A"}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    """构建最小图。

    START 和 END 是虚拟节点：
    - START：不执行任何逻辑，仅作为入口标记
    - END：不执行任何逻辑，仅作为终止标记
    它们不会出现在节点列表中，但必须通过边连接。
    """
    graph = StateGraph(State)
    graph.add_node("a", node_a)

    # START → a → END 构成最简单的线性拓扑
    graph.add_edge(START, "a")
    graph.add_edge("a", END)
    return graph


def main() -> None:
    graph = build_graph()

    # compile() 做了什么：
    # 1. 冻结拓扑结构，之后不能再 add_node / add_edge
    # 2. 校验所有边的合法性（节点是否存在、是否有孤立节点等）
    # 3. 返回一个可执行的 CompiledGraph 对象
    app = graph.compile()

    # invoke() 同步执行整个图，返回最终状态
    result = app.invoke({"message": "开始"})
    print(f"最终结果: {result}")


if __name__ == "__main__":
    main()
