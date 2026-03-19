"""Pregel 执行模型：superstep 概念与节点激活机制。

目标：理解 LangGraph 底层的 Pregel 执行模型
关键 API：StateGraph, stream（用于观察 superstep）
运行命令：python 03_execution_model.py
预期现象：打印每个 superstep 的执行过程，展示节点激活/休眠切换
生产提醒：同一 superstep 内的并行节点共享同一快照，互相看不到对方的写入
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- 状态定义 ----------
class State(TypedDict):
    value: int
    log: Annotated[list[str], operator.add]  # 追加语义，记录执行轨迹


# ---------- 节点函数 ----------
# Pregel 模型核心概念：
# - superstep：一轮同步执行，同一 superstep 内的节点并行运行
# - 节点激活：当入边有数据到达时，节点被激活（active）
# - channel 更新：节点输出写入 channel，在 superstep 边界才对下游可见

def step_one(state: State) -> dict:
    """Superstep 1：初始处理。"""
    print(f"  [step_one] 当前 value={state['value']}")
    return {"value": state["value"] * 2, "log": ["step_one: value * 2"]}


def step_two_a(state: State) -> dict:
    """Superstep 2（分支 A）：与 step_two_b 并行执行。"""
    print(f"  [step_two_a] 当前 value={state['value']}")
    return {"log": [f"step_two_a: 看到 value={state['value']}"]}


def step_two_b(state: State) -> dict:
    """Superstep 2（分支 B）：与 step_two_a 并行执行。"""
    print(f"  [step_two_b] 当前 value={state['value']}")
    return {"log": [f"step_two_b: 看到 value={state['value']}"]}


def step_three(state: State) -> dict:
    """Superstep 3：汇聚节点，等待两个分支都完成。"""
    print(f"  [step_three] 当前 value={state['value']}")
    return {"value": state["value"] + 100, "log": ["step_three: value + 100"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    """构建带并行分支的图，用于演示 superstep。

    拓扑结构：
        START → step_one → step_two_a → step_three → END
                         → step_two_b ↗
    step_two_a 和 step_two_b 在同一个 superstep 内并行执行。
    """
    graph = StateGraph(State)
    graph.add_node("step_one", step_one)
    graph.add_node("step_two_a", step_two_a)
    graph.add_node("step_two_b", step_two_b)
    graph.add_node("step_three", step_three)

    graph.add_edge(START, "step_one")
    # step_one 同时连接两个下游 → 它们在同一 superstep 并行
    graph.add_edge("step_one", "step_two_a")
    graph.add_edge("step_one", "step_two_b")
    # 两个分支汇聚到 step_three
    graph.add_edge("step_two_a", "step_three")
    graph.add_edge("step_two_b", "step_three")
    graph.add_edge("step_three", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    # 使用 astream 观察每个 superstep 的输出
    print("=== 使用 astream 观察 superstep 执行过程 ===\n")
    superstep = 0
    async for event in app.astream({"value": 5, "log": ["初始化"]}, stream_mode="updates"):
        superstep += 1
        print(f"\n--- Superstep {superstep} 输出 ---")
        for node_name, output in event.items():
            print(f"  节点 '{node_name}' 返回: {output}")

    # async-first 主线使用 ainvoke 获取最终结果
    print("\n=== ainvoke 最终结果 ===")
    result = await app.ainvoke({"value": 5, "log": ["初始化"]})
    print(f"value = {result['value']}")
    print(f"执行轨迹: {result['log']}")


if __name__ == "__main__":
    asyncio.run(main())
