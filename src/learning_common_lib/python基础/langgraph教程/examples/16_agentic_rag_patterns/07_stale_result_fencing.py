from __future__ import annotations

"""
目标：演示 stale result fencing。
关键 API：execution_id 校验、旧结果忽略、新结果接受
运行命令：python 07_stale_result_fencing.py
预期现象：
  1. stale 结果回写后，不推进 finalize
  2. current 结果回写后，图继续完成
生产提醒：
  - stale result 也要落审计，但不能污染当前计划
  - execution_id 是最小 fencing 主键
  - 更真实的生产路径还应叠加 task_id / plan_version / subtask_code
"""

import asyncio
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class FencingState(TypedDict, total=False):
    current_execution_id: str
    accepted_runs: list[str]
    stale_runs: list[str]
    incoming_result: dict | None
    next_action: str
    final_answer: str


def dispatch(state: FencingState) -> dict:
    return {"current_execution_id": "exec-current-002", "next_action": "wait"}


def wait_for_result(state: FencingState) -> dict:
    payload = interrupt({"current_execution_id": state["current_execution_id"]})
    return {"incoming_result": payload, "next_action": "evaluate"}


def evaluate_result(state: FencingState) -> dict:
    result = state["incoming_result"]
    execution_id = result["execution_id"]
    current_execution_id = state["current_execution_id"]
    print(
        f"[evaluate] incoming_execution_id={execution_id} "
        f"current_execution_id={current_execution_id}"
    )
    if execution_id != current_execution_id:
        print(f"[evaluate] stale result ignored: {execution_id}")
        return {
            "stale_runs": [*state.get("stale_runs", []), execution_id],
            "incoming_result": None,
            "next_action": "wait",
        }
    print(f"[evaluate] accepted result: {execution_id}")
    return {
        "accepted_runs": [*state.get("accepted_runs", []), execution_id],
        "next_action": "finalize",
    }


def finalize(state: FencingState) -> dict:
    return {"final_answer": f"accepted={state.get('accepted_runs', [])} stale={state.get('stale_runs', [])}"}


def route(state: FencingState) -> Literal["wait", "evaluate", "finalize"]:
    return state.get("next_action", "finalize")


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(FencingState)
    graph.add_node("dispatch", dispatch)
    graph.add_node("wait", wait_for_result)
    graph.add_node("evaluate", evaluate_result)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", route)
    graph.add_conditional_edges("wait", route)
    graph.add_conditional_edges("evaluate", route)
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "tenant:demo:task:fencing-001"}}

    print("=== 初次调用：进入等待态 ===")
    await app.ainvoke({"accepted_runs": [], "stale_runs": []}, config=config)

    print("\n=== 旧执行结果回写 ===")
    waiting_again = await app.ainvoke(
        Command(resume={"execution_id": "exec-old-001", "payload": "old"}),
        config=config,
    )
    print(f"stale_runs={waiting_again.get('stale_runs')}")

    print("\n=== 当前执行结果回写 ===")
    completed = await app.ainvoke(
        Command(resume={"execution_id": "exec-current-002", "payload": "fresh"}),
        config=config,
    )
    print(completed["final_answer"])


if __name__ == "__main__":
    asyncio.run(main())
