from __future__ import annotations

"""
目标：演示控制面真理源和 LangGraph runtime state 的职责分层。
关键 API：最小 graph state + 外部控制面记录
运行命令：python 05_control_plane_vs_runtime_state.py
预期现象：
  1. graph state 只保留 execution_ref / waiting_reason / latest_result_ref
  2. 控制面保留 task status / events / 审计信息
生产提醒：
  - checkpoint 不是业务真理源
  - 图越复杂，越需要把审计和恢复判定放到控制面
  - 本例中 CONTROL_PLANE 负责 status/events/current_execution_id，RuntimeState 只负责等待与恢复引用
"""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


CONTROL_PLANE: dict[str, dict] = {}


class RuntimeState(TypedDict, total=False):
    task_id: str
    execution_ref: dict
    waiting_reason: str
    latest_result_ref: dict | None
    final_answer: str


def dispatch(state: RuntimeState) -> dict:
    CONTROL_PLANE[state["task_id"]] = {
        "status": "WAITING_SUBTASKS",
        "events": ["task_submitted", "subtask_dispatched"],
        "current_execution_id": "exec-001",
    }
    return {
        "execution_ref": {
            "thread_id": f"tenant:demo:task:{state['task_id']}",
            "execution_id": "exec-001",
        },
        "waiting_reason": "SUBTASKS",
    }


def wait_for_result(state: RuntimeState) -> dict:
    result = interrupt(state["execution_ref"])
    return {"latest_result_ref": {"subtask_run_id": result["subtask_run_id"]}}


def finalize(state: RuntimeState) -> dict:
    CONTROL_PLANE[state["task_id"]]["status"] = "COMPLETED"
    CONTROL_PLANE[state["task_id"]]["events"].append("task_completed")
    return {"final_answer": f"最终答案引用 {state['latest_result_ref']}"}


async def main() -> None:
    graph = StateGraph(RuntimeState)
    graph.add_node("dispatch", dispatch)
    graph.add_node("wait", wait_for_result)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "dispatch")
    graph.add_edge("dispatch", "wait")
    graph.add_edge("wait", "finalize")
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=MemorySaver())

    config = {"configurable": {"thread_id": "tenant:demo:task:101"}}
    waiting = await app.ainvoke({"task_id": "101"}, config=config)
    print("=== runtime state ===")
    print(f"  execution_ref={waiting.get('execution_ref')}")
    print(f"  waiting_reason={waiting.get('waiting_reason')}")
    print(f"  latest_result_ref={waiting.get('latest_result_ref')}")
    print("\n=== control plane ===")
    print(CONTROL_PLANE["101"])

    completed = await app.ainvoke(
        Command(resume={"subtask_run_id": 3001}),
        config=config,
    )
    print("\n=== 完成后 ===")
    print(f"  final_answer={completed['final_answer']}")
    print(f"  latest_result_ref={completed.get('latest_result_ref')}")
    print(f"  control_plane={CONTROL_PLANE['101']}")


if __name__ == "__main__":
    asyncio.run(main())
