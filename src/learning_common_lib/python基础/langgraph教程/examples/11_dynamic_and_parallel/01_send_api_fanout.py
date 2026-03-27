"""
Send API 动态 fan-out 并行分发

目标:
    演示 Send API 实现 map-reduce 模式，将不同输入动态分发到多个 worker 并行处理。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    - Send(node_name, state) —— 路由函数中动态创建并行分支
    - add_conditional_edges(...) —— 将 dispatch 结果 fan-out 到 worker
    - reducer（Annotated list）—— 聚合并行结果

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/11_dynamic_and_parallel/01_send_api_fanout.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/11_dynamic_and_parallel/01_send_api_fanout.py

预期现象:
    scatter 节点根据任务列表动态分发 3 个 worker，每个 worker 独立处理后
    结果汇聚到 gather 节点输出聚合结果。

生产提醒:
    - Send 的数量没有硬性上限，但过多并行分支会占用大量内存
    - 每个 Send 分支拥有独立的状态副本，修改不会互相影响
    - 生产环境建议配合 checkpointer 使用，确保中间状态可恢复
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send


# ── 状态定义 ──────────────────────────────────────────────
class WorkerState(TypedDict):
    """单个 worker 的输入状态"""
    task: str


class MainState(TypedDict):
    """主图状态：tasks 是待处理列表，results 通过 reducer 聚合"""
    tasks: list[str]
    queued_tasks: list[str]
    batch: int
    results: Annotated[list[str], operator.add]  # 多个 worker 的结果自动合并


# ── 节点函数 ──────────────────────────────────────────────
def scatter_node(state: MainState) -> dict:
    """准备 fan-out 所需的批次信息。"""
    batch = state.get("batch", 0) + 1
    queued_tasks = list(state["tasks"])
    print(f"[scatter] 第 {batch} 批收到 {len(queued_tasks)} 个任务，开始分发...")
    return {"queued_tasks": queued_tasks, "batch": batch}


def scatter_route(state: MainState) -> list[Send]:
    """将 queued_tasks 动态 fan-out 到 worker。"""
    return [Send("worker", {"task": task}) for task in state.get("queued_tasks", [])]


def worker_node(state: WorkerState) -> dict:
    """模拟 worker 处理单个任务"""
    task = state["task"]
    result = f"已完成: {task.upper()}"
    print(f"  [worker] 处理任务 '{task}' -> '{result}'")
    return {"results": [result]}


def gather_node(state: MainState) -> dict:
    """聚合所有 worker 的结果"""
    print(f"[gather] 收到 {len(state['results'])} 个结果，聚合完成")
    return {}


# ── 构建图 ──────────────────────────────────────────────
def build_fanout_graph() -> StateGraph:
    graph = StateGraph(MainState)

    graph.add_node("scatter", scatter_node)
    graph.add_node("worker", worker_node)
    graph.add_node("gather", gather_node)

    graph.set_entry_point("scatter")
    graph.add_conditional_edges("scatter", scatter_route, ["worker"])
    graph.add_edge("worker", "gather")
    graph.add_edge("gather", END)

    return graph.compile()


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    async def main() -> None:
        app = build_fanout_graph()

        initial_state: MainState = {
            "tasks": ["翻译文档", "生成摘要", "提取关键词"],
            "queued_tasks": [],
            "batch": 0,
            "results": [],
        }

        print("=== Send API Fan-out 演示 ===\n")
        result = await app.ainvoke(initial_state)

        print(f"\n最终结果: {result['results']}")

    asyncio.run(main())
