"""
Channel 类型深入：LastValue、BinaryOperator、EphemeralValue。

目标:
    理解 LangGraph 底层的 Channel 抽象

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    Channels（概念层面）、Annotated reducers（用户层面）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/02_state_deep_dive/05_state_channels.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/02_state_deep_dive/05_state_channels.py

预期现象:
    演示三种 channel 语义的行为差异

生产提醒:
    大多数场景用 Annotated + reducer 即可，无需直接操作 Channel
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


# ---------- Channel 类型说明 ----------
# LangGraph 的状态字段底层对应不同的 Channel 类型：
#
# 1. LastValue（默认）：保留最后写入的值，无 reducer 时的默认行为
# 2. BinaryOperatorAggregate：通过 reducer 函数归约，对应 Annotated[type, reducer]
# 3. EphemeralValue：仅在当前 superstep 可见，下一步自动清除

# ---------- 状态定义 ----------
class State(TypedDict):
    # LastValue 语义：无 reducer，last-write-wins
    current_step: str

    # BinaryOperatorAggregate 语义：通过 operator.add 追加
    history: Annotated[list[str], operator.add]

    # 模拟 EphemeralValue：每个节点读取后清除
    # LangGraph 没有直接暴露 EphemeralValue API，
    # 但可以通过节点逻辑模拟：读取后返回空值
    temp_signal: str


# ---------- 节点函数 ----------
def producer(state: State) -> dict:
    """生产者：写入所有 channel。"""
    print(f"[producer] 写入信号: 'GO'")
    return {
        "current_step": "producer",
        "history": ["producer 执行"],
        "temp_signal": "GO",
    }


def consumer_a(state: State) -> dict:
    """消费者 A：读取信号并清除（模拟 ephemeral）。"""
    signal = state.get("temp_signal", "")
    print(f"[consumer_a] 读到信号: '{signal}'")
    return {
        "current_step": "consumer_a",
        "history": [f"consumer_a 读到信号='{signal}'"],
        "temp_signal": "",  # 清除信号，模拟 ephemeral
    }


def consumer_b(state: State) -> dict:
    """消费者 B：读取信号（此时已被 A 清除）。"""
    signal = state.get("temp_signal", "")
    print(f"[consumer_b] 读到信号: '{signal}'")
    return {
        "current_step": "consumer_b",
        "history": [f"consumer_b 读到信号='{signal}'"],
    }


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    """线性链：producer → consumer_a → consumer_b。"""
    graph = StateGraph(State)
    graph.add_node("producer", producer)
    graph.add_node("consumer_a", consumer_a)
    graph.add_node("consumer_b", consumer_b)
    graph.add_edge(START, "producer")
    graph.add_edge("producer", "consumer_a")
    graph.add_edge("consumer_a", "consumer_b")
    graph.add_edge("consumer_b", END)
    return graph


async def main() -> None:
    app = build_graph().compile()
    result = await app.ainvoke({
        "current_step": "",
        "history": [],
        "temp_signal": "",
    })

    print("\n=== 最终结果 ===")
    print(f"current_step (LastValue): '{result['current_step']}'")
    print(f"  → 只保留最后写入的值")
    print(f"history (BinaryOperator): {result['history']}")
    print(f"  → 通过 operator.add 累积所有写入")
    print(f"temp_signal (模拟 Ephemeral): '{result['temp_signal']}'")
    print(f"  → consumer_a 清除后，consumer_b 读到空值")


if __name__ == "__main__":
    asyncio.run(main())
