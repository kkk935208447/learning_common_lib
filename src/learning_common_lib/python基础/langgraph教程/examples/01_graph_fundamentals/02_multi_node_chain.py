"""
三节点链式图：状态在节点间自动传递。

目标:
    理解多节点链式执行与 partial state 返回机制

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph, add_node, add_edge, compile, invoke

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/01_graph_fundamentals/02_multi_node_chain.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/01_graph_fundamentals/02_multi_node_chain.py

预期现象:
    消息依次经过三个节点，每个节点追加文本；step 计数递增

生产提醒:
    无 reducer 时字段采用 last-write-wins 策略，多节点并行写同一字段会丢失数据
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 状态定义 ----------
class State(TypedDict):
    message: str
    step: int


# ---------- 节点函数 ----------
# 每个节点只返回需要更新的字段（partial state），
# LangGraph 自动将返回值合并到当前状态。
# 无 reducer 时，同名字段直接覆盖（last-write-wins）。

def node_a(state: State) -> dict:
    """节点 A：第一步处理。"""
    print(f"[节点A] step={state.get('step', 0)}, message={state['message']}")
    return {
        "message": state["message"] + " -> A",
        "step": state.get("step", 0) + 1,
    }


def node_b(state: State) -> dict:
    """节点 B：第二步处理。"""
    print(f"[节点B] step={state['step']}, message={state['message']}")
    return {
        "message": state["message"] + " -> B",
        "step": state["step"] + 1,
    }


def node_c(state: State) -> dict:
    """节点 C：第三步处理。"""
    print(f"[节点C] step={state['step']}, message={state['message']}")
    return {
        "message": state["message"] + " -> C",
        "step": state["step"] + 1,
    }


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_node("c", node_c)

    # 线性链：START → A → B → C → END
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("c", END)
    return graph


def main() -> None:
    app = build_graph().compile()
    result = app.invoke({"message": "开始", "step": 0})
    print(f"\n最终结果: message='{result['message']}', step={result['step']}")


if __name__ == "__main__":
    main()
