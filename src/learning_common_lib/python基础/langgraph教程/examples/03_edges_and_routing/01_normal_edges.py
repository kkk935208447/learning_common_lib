"""普通边、入口点边、END 边。

目标：掌握 LangGraph 中三种基本边类型及新旧 API 对比
关键 API：add_edge, set_entry_point（旧）, set_finish_point（旧）, START/END（新）
运行命令：python 01_normal_edges.py
预期现象：新旧两种 API 构建相同拓扑，输出一致
生产提醒：set_entry_point/set_finish_point 是旧 API，推荐使用 START/END 常量
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    value: str


def step_a(state: State) -> dict:
    print(f"[A] value='{state['value']}'")
    return {"value": state["value"] + " -> A"}


def step_b(state: State) -> dict:
    print(f"[B] value='{state['value']}'")
    return {"value": state["value"] + " -> B"}


def step_c(state: State) -> dict:
    print(f"[C] value='{state['value']}'")
    return {"value": state["value"] + " -> C"}


def demo_new_api() -> None:
    """新 API：使用 START/END 常量（推荐）。"""
    print("=== 新 API (START/END 常量) ===")
    graph = StateGraph(State)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.add_node("c", step_c)

    # 普通边：节点间的固定连接
    graph.add_edge(START, "a")  # 入口边：START → a
    graph.add_edge("a", "b")   # 普通边：a → b
    graph.add_edge("b", "c")   # 普通边：b → c
    graph.add_edge("c", END)   # 终止边：c → END

    app = graph.compile()
    result = app.invoke({"value": "开始"})
    print(f"结果: {result['value']}\n")


def demo_old_api() -> None:
    """旧 API：使用 set_entry_point / set_finish_point。"""
    print("=== 旧 API (set_entry_point/set_finish_point) ===")
    graph = StateGraph(State)
    graph.add_node("a", step_a)
    graph.add_node("b", step_b)
    graph.add_node("c", step_c)

    # 旧 API（仍可用，但不推荐）
    graph.set_entry_point("a")   # 等价于 add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.set_finish_point("c")  # 等价于 add_edge("c", END)

    app = graph.compile()
    result = app.invoke({"value": "开始"})
    print(f"结果: {result['value']}\n")


def main() -> None:
    demo_new_api()
    demo_old_api()
    print("两种 API 产生相同的拓扑结构和执行结果")


if __name__ == "__main__":
    main()
