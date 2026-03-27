from __future__ import annotations

"""
目标：演示 resume / replay 相关测试。
关键 API：MemorySaver、interrupt、Command(resume=...)
运行命令：python 05_resume_and_replay_tests.py
预期现象：
  1. 同一 thread_id 能正确恢复
  2. 不同 thread_id 不会串线
  3. full fencing tuple 能拦住旧执行结果
  4. duplicate resume 不会重复处理相同 result_ref
"""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import accept_or_mark_stale
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import accept_or_mark_stale


class ResumeState(TypedDict, total=False):
    current_execution_id: str
    result: str


def wait_for_result(state: ResumeState) -> dict:
    payload = interrupt({"execution_id": state["current_execution_id"]})
    return {"result": payload["result"]}


def duplicate_resume_guard(result_ref: str, seen_result_refs: set[str]) -> bool:
    if result_ref in seen_result_refs:
        return False
    seen_result_refs.add(result_ref)
    return True


async def test_resume_same_thread() -> None:
    saver = MemorySaver()
    graph = StateGraph(ResumeState)
    graph.add_node("wait", wait_for_result)
    graph.add_edge(START, "wait")
    graph.add_edge("wait", END)
    app = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "resume-test"}}
    waiting = await app.ainvoke({"current_execution_id": "exec-001"}, config=config)
    assert waiting["current_execution_id"] == "exec-001"
    resumed = await app.ainvoke(Command(resume={"result": "done"}), config=config)
    assert resumed["result"] == "done"
    print("[PASS] test_resume_same_thread")


async def test_thread_isolation() -> None:
    saver = MemorySaver()
    graph = StateGraph(ResumeState)
    graph.add_node("wait", wait_for_result)
    graph.add_edge(START, "wait")
    graph.add_edge("wait", END)
    app = graph.compile(checkpointer=saver)

    await app.ainvoke({"current_execution_id": "exec-a"}, config={"configurable": {"thread_id": "A"}})
    await app.ainvoke({"current_execution_id": "exec-b"}, config={"configurable": {"thread_id": "B"}})
    state_a = await app.aget_state({"configurable": {"thread_id": "A"}})
    state_b = await app.aget_state({"configurable": {"thread_id": "B"}})
    assert state_a.values["current_execution_id"] == "exec-a"
    assert state_b.values["current_execution_id"] == "exec-b"
    print("[PASS] test_thread_isolation")


def test_full_fencing_tuple() -> None:
    accepted = accept_or_mark_stale(
        {
            "task_id": "task-1",
            "execution_id": "exec-002",
            "status": "COMPLETED",
            "result_payload": {"plan_version": 1, "subtask_code": "ST-001"},
        },
        current_execution_id="exec-002",
        current_task_id="task-1",
        current_plan_version=1,
        current_subtask_code="ST-001",
    )
    stale = accept_or_mark_stale(
        {
            "task_id": "task-old",
            "execution_id": "exec-001",
            "status": "COMPLETED",
            "result_payload": {"plan_version": 0, "subtask_code": "ST-OLD"},
        },
        current_execution_id="exec-002",
        current_task_id="task-1",
        current_plan_version=1,
        current_subtask_code="ST-001",
    )
    assert accepted["accepted"] is True
    assert stale["accepted"] is False
    print("[PASS] test_full_fencing_tuple")


def test_duplicate_resume_guard() -> None:
    seen: set[str] = set()
    assert duplicate_resume_guard("run://3001", seen) is True
    assert duplicate_resume_guard("run://3001", seen) is False
    assert duplicate_resume_guard("run://3002", seen) is True
    print("[PASS] test_duplicate_resume_guard")


async def main() -> None:
    await test_resume_same_thread()
    await test_thread_isolation()
    test_full_fencing_tuple()
    test_duplicate_resume_guard()


if __name__ == "__main__":
    asyncio.run(main())
