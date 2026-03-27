"""
05_checkpointing / 06_subgraph_thread_strategy

目标:
    演示 GlobalGraph / SubtaskGraph 的 thread_id 规范。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    同一个 checkpointer、不同 thread_id、aget_state()

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/06_subgraph_thread_strategy.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/05_checkpointing/06_subgraph_thread_strategy.py

预期现象:
    1. GlobalGraph 和两个子任务图分别写入不同 thread_id
    2. checkpoint 相互隔离，不会串状态

生产提醒:
    - 父图和子图不能共用同一个 thread_id
    - 不同 execution_id 的子任务更不能复用同一 subtask thread_id
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

try:
    from ...templates import DEFAULT_RUNTIME_SETTINGS
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import DEFAULT_RUNTIME_SETTINGS


class GlobalState(TypedDict, total=False):
    task_id: str
    next_action: str


class SubtaskState(TypedDict, total=False):
    subtask_code: str
    execution_id: str
    result: str


def global_node(state: GlobalState) -> dict:
    return {"next_action": "dispatch_subtasks"}


def subtask_node(state: SubtaskState) -> dict:
    return {
        "result": f"{state.get('subtask_code')}@{state.get('execution_id')} 完成"
    }


async def main() -> None:
    saver = MemorySaver()
    global_thread = DEFAULT_RUNTIME_SETTINGS.global_thread_id("acme", 42)
    subtask_thread_1 = DEFAULT_RUNTIME_SETTINGS.subtask_thread_id(
        "acme", 42, 1, "ST-001", "exec-001"
    )
    subtask_thread_2 = DEFAULT_RUNTIME_SETTINGS.subtask_thread_id(
        "acme", 42, 1, "ST-001", "exec-002"
    )

    global_graph = StateGraph(GlobalState)
    global_graph.add_node("orchestrate", global_node)
    global_graph.add_edge(START, "orchestrate")
    global_graph.add_edge("orchestrate", END)
    compiled_global = global_graph.compile(checkpointer=saver)

    subtask_graph = StateGraph(SubtaskState)
    subtask_graph.add_node("execute", subtask_node)
    subtask_graph.add_edge(START, "execute")
    subtask_graph.add_edge("execute", END)
    compiled_subtask = subtask_graph.compile(checkpointer=saver)

    await compiled_global.ainvoke({"task_id": "42"}, config={"configurable": {"thread_id": global_thread}})
    await compiled_subtask.ainvoke(
        {"subtask_code": "ST-001", "execution_id": "exec-001"},
        config={"configurable": {"thread_id": subtask_thread_1}},
    )
    await compiled_subtask.ainvoke(
        {"subtask_code": "ST-001", "execution_id": "exec-002"},
        config={"configurable": {"thread_id": subtask_thread_2}},
    )

    global_state = await compiled_global.aget_state({"configurable": {"thread_id": global_thread}})
    subtask_state_1 = await compiled_subtask.aget_state({"configurable": {"thread_id": subtask_thread_1}})
    subtask_state_2 = await compiled_subtask.aget_state({"configurable": {"thread_id": subtask_thread_2}})

    print("=== thread_id 规范 ===")
    print(f"global_thread:  {global_thread}")
    print(f"subtask_thread: {subtask_thread_1}")
    print(f"subtask_thread: {subtask_thread_2}\n")

    print("=== checkpoint 隔离结果 ===")
    print(f"GlobalState:  {global_state.values}")
    print(f"SubtaskState(exec-001): {subtask_state_1.values}")
    print(f"SubtaskState(exec-002): {subtask_state_2.values}")


if __name__ == "__main__":
    asyncio.run(main())
