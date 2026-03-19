"""Send API 动态 fan-out 并行分发

目标：
    演示 Send API 实现 map-reduce 模式，将不同输入动态分发到多个 worker 并行处理。

关键 API：
    - Send(node_name, state) —— 动态创建并行分支
    - reducer（Annotated list）—— 聚合并行结果

运行命令：
    python 01_send_api_fanout.py

预期现象：
    scatter 节点根据任务列表动态分发 3 个 worker，每个 worker 独立处理后
    结果汇聚到 gather 节点输出聚合结果。

生产提醒：
    - Send 的数量没有硬性上限，但过多并行分支会占用大量内存
    - 每个 Send 分支拥有独立的状态副本，修改不会互相影响
    - 生产环境建议配合 checkpointer 使用，确保中间状态可恢复
"""
from __future__ import annotations

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
    results: Annotated[list[str], operator.add]  # 多个 worker 的结果自动合并


# ── 节点函数 ──────────────────────────────────────────────
def scatter_node(state: MainState) -> list[Send]:
    """根据任务列表动态分发到 worker 节点

    返回 list[Send] 时，LangGraph 会为每个 Send 创建一个并行分支。
    每个分支独立执行，互不干扰。
    """
    print(f"[scatter] 收到 {len(state['tasks'])} 个任务，开始分发...")
    return [Send("worker", {"task": task}) for task in state["tasks"]]


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
    # scatter 返回 list[Send]，LangGraph 自动处理并行分发
    graph.add_conditional_edges("scatter", scatter_node, ["worker"])
    graph.add_edge("worker", "gather")
    graph.add_edge("gather", END)

    return graph.compile()


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    app = build_fanout_graph()

    initial_state: MainState = {
        "tasks": ["翻译文档", "生成摘要", "提取关键词"],
        "results": [],
    }

    print("=== Send API Fan-out 演示 ===\n")
    result = app.invoke(initial_state)

    print(f"\n最终结果: {result['results']}")
    # 预期输出: ['已完成: 翻译文档', '已完成: 生成摘要', '已完成: 提取关键词']
