"""
循环边 + 迭代守卫 + 收敛检测。

目标:
    实现带安全守卫的循环图，防止无限循环

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    add_conditional_edges, 循环边

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/03_edges_and_routing/04_loop_with_guard.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/03_edges_and_routing/04_loop_with_guard.py

预期现象:
    循环迭代直到达到最大次数或检测到状态收敛（fingerprint 重复）

生产提醒:
    生产环境务必设置 max_iterations 和收敛检测，避免 LLM 陷入死循环
"""
from __future__ import annotations

import asyncio
import hashlib
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    data: str
    iteration: int
    max_iterations: int
    fingerprint: str
    historical_fingerprints: Annotated[list[str], operator.add]
    log: Annotated[list[str], operator.add]


# ---------- 路由函数 ----------
def loop_guard_router(state: State) -> str:
    """循环守卫路由器。

    两种退出条件：
    1. 达到最大迭代次数
    2. 检测到状态收敛（fingerprint 与历史重复）
    """
    if state["iteration"] >= state["max_iterations"]:
        print(f"  [guard] 达到最大迭代次数 {state['max_iterations']}，退出")
        return "exit"

    fp = state.get("fingerprint", "")
    history = state.get("historical_fingerprints", [])
    # 检查当前 fingerprint 是否在历史中出现过（排除最后一个，即自身）
    if fp and fp in history[:-1]:
        print(f"  [guard] 检测到状态收敛（fingerprint 重复），退出")
        return "exit"

    return "continue"


# ---------- 节点函数 ----------
def process_node(state: State) -> dict:
    """处理节点：模拟迭代优化。"""
    iteration = state["iteration"] + 1
    # 模拟数据处理：每次迭代追加内容
    new_data = state["data"] + f"[iter{iteration}]"

    # 计算 fingerprint 用于收敛检测
    fp = hashlib.md5(new_data.encode()).hexdigest()[:8]

    print(f"  [process] 迭代 {iteration}: data='{new_data}', fp={fp}")
    return {
        "data": new_data,
        "iteration": iteration,
        "fingerprint": fp,
        "historical_fingerprints": [fp],
        "log": [f"迭代{iteration}: fp={fp}"],
    }


def exit_node(state: State) -> dict:
    """退出节点：汇总结果。"""
    print(f"  [exit] 共迭代 {state['iteration']} 次")
    return {"log": [f"退出: 共{state['iteration']}次迭代"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    """构建带循环守卫的图。

    拓扑：START → process → (guard) → process（循环）
                                    → exit → END
    """
    graph = StateGraph(State)
    graph.add_node("process", process_node)
    graph.add_node("exit", exit_node)

    graph.add_edge(START, "process")
    graph.add_conditional_edges(
        "process",
        loop_guard_router,
        {"continue": "process", "exit": "exit"},
    )
    graph.add_edge("exit", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    # 演示 1：达到最大迭代次数退出
    print("=== 演示 1: 最大迭代次数守卫 (max=3) ===")
    result = await app.ainvoke({
        "data": "初始",
        "iteration": 0,
        "max_iterations": 3,
        "fingerprint": "",
        "historical_fingerprints": [],
        "log": [],
    })
    print(f"执行轨迹: {result['log']}")
    print(f"最终数据: {result['data']}\n")

    # 演示 2：收敛检测退出（预置相同 fingerprint，模拟状态收敛）
    print("=== 演示 2: 收敛检测守卫 ===")
    first_iteration_fp = hashlib.md5("初始[iter1]".encode()).hexdigest()[:8]
    result = await app.ainvoke({
        "data": "初始",
        "iteration": 0,
        "max_iterations": 100,  # 给足上限，让收敛检测优先生效
        "fingerprint": first_iteration_fp,
        "historical_fingerprints": [first_iteration_fp],
        "log": [],
    })
    print(f"执行轨迹: {result['log']}")
    print(f"共迭代: {result['iteration']} 次")


if __name__ == "__main__":
    asyncio.run(main())
