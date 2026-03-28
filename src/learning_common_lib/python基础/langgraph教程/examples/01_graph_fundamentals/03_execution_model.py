"""
Pregel 执行模型：superstep 概念与节点激活机制，fan-out/fan-in 语义。

目标:
    理解 LangGraph 底层的 Pregel 执行模型

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph, astream(stream_mode="updates")（观察节点级更新流，见 main 中注释）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/01_graph_fundamentals/03_execution_model.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/01_graph_fundamentals/03_execution_model.py

预期现象:
    按 stream 事件打印 updates；fan-out 两节点常各占一条事件。节点内 print 可能与「--- 第 N 条 ---」
    标题交错，属 stdout 与异步流顺序问题，不代表调度语义错误。
    这里应重点观察「step_two_a / step_two_b 看到同一输入快照」，而不是把输出顺序误当成
    “一定物理并行”或“一定串行”。

生产提醒:
    同一 superstep 内的并行节点共享同一快照，互相看不到对方的写入
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
# Pregel 模型核心概念（引擎内部 superstep，与下面 main 里手写的「第几条 stream」不是同一计数）：
# - superstep：一轮“图语义上的同步波次”
#   重点是：同一波次里被激活的节点共享同一输入快照，互相看不到彼此本轮写入
#   不要把它简单理解成“你一定能观察到物理上的同时执行”
# - 是否物理并行：取决于运行时调度、节点类型(sync/async)、执行器等实现细节
#   教程里不把“物理并行”当成保证项，只强调 superstep 语义
# - 节点激活：当入边有数据到达时，节点被激活（active）
# - channel 更新：节点输出写入 channel，在 superstep 边界才对下游可见

def step_one(state: State) -> dict:
    """入口：将 value 放大（图内第一波）。"""
    print(f"  [step_one] 当前 value={state['value']}")
    return {"value": state["value"] * 2, "log": ["step_one: value * 2"]}


def step_two_a(state: State) -> dict:
    """fan-out 分支 A（与 step_two_b 同 wave）。"""
    print(f"  [step_two_a] 当前 value={state['value']}")
    return {"log": [f"step_two_a: 看到 value={state['value']}"]}


def step_two_b(state: State) -> dict:
    """fan-out 分支 B（与 step_two_a 同 wave）。"""
    print(f"  [step_two_b] 当前 value={state['value']}")
    return {"log": [f"step_two_b: 看到 value={state['value']}"]}


def step_three(state: State) -> dict:
    """fan-in：两分支都到齐后执行。"""
    print(f"  [step_three] 当前 value={state['value']}")
    return {"value": state["value"] + 100, "log": ["step_three: value + 100"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    """构建带并行分支的图，用于演示 superstep。

    拓扑结构：
        START → step_one → step_two_a → step_three → END
                         → step_two_b ↗
    step_two_a 与 step_two_b 为 fan-out：在图语义上，它们属于同一 wave / 同一 superstep。它们都会看到 step_one 写回后的同一份快照（这里是 value * 2 之后的值）。但这不等于教程层面承诺“你一定会观察到物理并行”
    换句话说，本例要学习的是“同一波次快照一致 + fan-in 需等上游都完成”，而不是依赖 print 顺序去判断线程/任务是否真的同时执行。
    另外，astream(..., updates) 往往按节点分多条事件推送，不要把「第几条 stream 事件」当成引擎内部 superstep 编号。
    """
    graph = StateGraph(State)
    graph.add_node("step_one", step_one)
    graph.add_node("step_two_a", step_two_a)
    graph.add_node("step_two_b", step_two_b)
    graph.add_node("step_three", step_three)

    graph.add_edge(START, "step_one")
    # step_one 同时连接两个下游：语义上：step_two_a / step_two_b 同属下一 wave。保证项：它们看到同一输入快照。非保证项：stdout 的先后顺序、是否肉眼可见“同时执行”
    graph.add_edge("step_one", "step_two_a")
    graph.add_edge("step_one", "step_two_b")
    # 两个分支汇聚到 step_three
    graph.add_edge("step_two_a", "step_three")
    graph.add_edge("step_two_b", "step_three")
    graph.add_edge("step_three", END)
    return graph


async def main() -> None:
    app = build_graph().compile()
    # 导出 langgraph 图
    get_langgraph_png(app, "03_execution_model.png")

    # stream_mode="updates"：每 yield 一次通常对应「至少一个节点」写回。fan-out 分支常拆成多条 updates 事件
    #
    # 下面的 stream_idx 计数的是「第几条 stream 事件」，不是 Pregel 引擎内部的 superstep 序号。
    # 节点函数里的 print 一执行就输出；「--- 第 N 条 ---」要等该次 yield 返回后才打印，所以二者可能交错。
    #
    # 正确观察方式：step_two_a / step_two_b 都应看到 value=10（来自 step_one）。不要根据它们谁先 print，就推断“引擎一定串行”或“一定物理并行”
    print("=== 使用 astream(stream_mode='updates') 观察节点更新流 ===\n")
    stream_idx = 0
    async for event in app.astream({"value": 5, "log": ["初始化"]}, stream_mode="updates"):
        stream_idx += 1
        print(f"\n--- 第 {stream_idx} 条 stream 事件（updates）---")
        for node_name, output in event.items():
            print(f"  节点 '{node_name}' 返回: {output}")

    # async-first 主线使用 ainvoke 获取最终结果
    print("\n=== ainvoke 最终结果 ===")
    result = await app.ainvoke({"value": 5, "log": ["初始化"]})
    print(f"value = {result['value']}")
    print(f"执行轨迹: {result['log']}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    # 画图 png
    app.get_graph().draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
