"""
16_agentic_rag_patterns / 06_resume_orchestrator_contract

目标:
    演示 resume_orchestrator 的最小契约。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    result envelope、同一 thread_id 恢复

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/16_agentic_rag_patterns/06_resume_orchestrator_contract.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/16_agentic_rag_patterns/06_resume_orchestrator_contract.py

预期现象:
    1. 图先进入等待态
    2. 外部恢复器接收 ResumeEnvelope
    3. 恢复器先记录 accepted 事件，再用同一 thread_id 恢复图

生产提醒:
    - resume_orchestrator 只负责 accepted + resume，不负责自己做调度决策
    - 这个例子故意不演示调度，只聚焦 accepted + resume 契约
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import ResumeEnvelope
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import ResumeEnvelope


TASK_EVENTS: list[str] = []


class ResumeState(TypedDict, total=False):
    execution_id: str
    worker_result: str
    final_answer: str


def dispatch(state: ResumeState) -> dict:
    TASK_EVENTS.append("subtask_dispatched")
    return {"execution_id": "exec-resume-001"}


def wait(state: ResumeState) -> dict:
    envelope = interrupt({"execution_id": state["execution_id"]})
    return {"worker_result": envelope["result_payload"]["summary"]}


def finalize(state: ResumeState) -> dict:
    TASK_EVENTS.append("task_completed")
    return {"final_answer": f"恢复后汇总：{state['worker_result']}"}


async def resume_orchestrator(
    *,
    app,
    config: dict,
    result: ResumeEnvelope,
) -> dict:
    print(f"[resume_orchestrator] before events={TASK_EVENTS}")
    TASK_EVENTS.append(
        f"subtask_result_accepted:{result['execution_id']}:{result['status']}"
    )
    resumed = await app.ainvoke(Command(resume=result), config=config)
    print(f"[resume_orchestrator] after events={TASK_EVENTS}")
    print(f"[resume_orchestrator] resumed_state={resumed}")
    return resumed


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(ResumeState)
    graph.add_node("dispatch", dispatch)
    graph.add_node("wait", wait)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "dispatch")
    graph.add_edge("dispatch", "wait")
    graph.add_edge("wait", "finalize")
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "tenant:demo:task:resume-001"}}
    await app.ainvoke({}, config=config)

    result = await resume_orchestrator(
        app=app,
        config=config,
        result={
            "thread_id": "tenant:demo:task:resume-001",
            "execution_id": "exec-resume-001",
            "task_id": "task-001",
            "status": "COMPLETED",
            "result_ref": "run://3001",
            "result_payload": {"summary": "worker 已完成 2 条证据整理"},
        },
    )
    print(result["final_answer"])
    print(TASK_EVENTS)


if __name__ == "__main__":
    asyncio.run(main())
