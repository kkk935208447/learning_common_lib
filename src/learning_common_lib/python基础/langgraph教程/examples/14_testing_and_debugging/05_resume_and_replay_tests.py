from __future__ import annotations

"""
目标：演示 resume / replay 相关测试。
关键 API：MemorySaver、interrupt、Command(resume=...)
运行命令：python 05_resume_and_replay_tests.py
预期现象：
  1. 同一 thread_id 能正确恢复
  2. 不同 thread_id 不会串线
  3. stale result helper 能拦住旧执行结果
"""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ResumeState(TypedDict, total=False):
    current_execution_id: str
    result: str


def wait_for_result(state: ResumeState) -> dict:
    payload = interrupt({"execution_id": state["current_execution_id"]})
    return {"result": payload["result"]}


def stale_guard(result_execution_id: str, current_execution_id: str) -> bool:
    return result_execution_id == current_execution_id


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


def test_stale_result_guard() -> None:
    assert stale_guard("exec-002", "exec-002") is True
    assert stale_guard("exec-001", "exec-002") is False
    print("[PASS] test_stale_result_guard")


async def main() -> None:
    await test_resume_same_thread()
    await test_thread_isolation()
    test_stale_result_guard()


if __name__ == "__main__":
    asyncio.run(main())
