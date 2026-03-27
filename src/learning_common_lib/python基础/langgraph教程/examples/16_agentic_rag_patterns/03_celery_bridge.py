"""LangGraph + Celery 桥接模式（完整 fencing + duplicate resume 版）。

目标：
    演示“分发 -> 等待 -> 外部结果回写 -> accepted/stale 判定 -> 恢复”链路。

关键点：
    - fencing 主键不只看 execution_id，还看 task_id / plan_version / subtask_code
    - duplicate resume 不应重复推进 finalize
    - 中间态打印必须让读者看见 waiting snapshot 和 accepted/stale 差异
    - 本例仍故意省略 maintenance/reaper/outbox 补偿，只聚焦恢复主链和 fencing
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        DispatchEnvelope,
        ResumeEnvelope,
        accept_or_mark_stale,
    )
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        DispatchEnvelope,
        ResumeEnvelope,
        accept_or_mark_stale,
    )

STRICT_REDIS = DEFAULT_RUNTIME_SETTINGS.strict_redis


def emit_runtime_status(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    line = f"RUNTIME_STATUS checkpoint={backend} degraded={degraded} strict={STRICT_REDIS}"
    if last_error:
        line += f" last_error={last_error}"
    print(line)


def require_real_redis(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    emit_runtime_status(backend=backend, degraded=degraded, last_error=last_error)
    if STRICT_REDIS and (backend != "redis" or degraded):
        raise RuntimeError(
            "Celery bridge 集成示例要求真实 Redis checkpoint；"
            f"backend={backend}, degraded={degraded}, last_error={last_error}"
        )


class BridgeState(TypedDict, total=False):
    task_id: str
    plan_version: int
    subtask_code: str
    query: str
    thread_id: str
    current_execution_id: str
    dispatch_envelope: DispatchEnvelope
    waiting_reason: str
    latest_resume: ResumeEnvelope | None
    accepted_results: list[str]
    stale_results: list[str]
    processed_resume_ids: list[str]
    next_action: str
    final_result: str


def dispatch(state: BridgeState) -> dict:
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    envelope: DispatchEnvelope = {
        "task_id": f"celery-{uuid.uuid4().hex[:8]}",
        "thread_id": state["thread_id"],
        "execution_id": execution_id,
        "queue": "subtask_jobs",
        "task_name": "execute_subtask",
        "status": "DISPATCHED",
        "plan_version": state["plan_version"],
        "subtask_code": state["subtask_code"],
    }
    print(f"[dispatch] envelope={envelope}")
    return {
        "current_execution_id": execution_id,
        "dispatch_envelope": envelope,
        "waiting_reason": "SUBTASK_RESULT",
        "next_action": "wait",
    }


def wait_for_result(state: BridgeState) -> dict:
    if state.get("latest_resume"):
        print(f"[wait] latest_resume 已写回: {state['latest_resume']}")
        return {"next_action": "evaluate"}
    result = interrupt(
        {
            "thread_id": state["thread_id"],
            "execution_id": state["current_execution_id"],
            "waiting_reason": state["waiting_reason"],
            "task_id": state["task_id"],
            "plan_version": state["plan_version"],
            "subtask_code": state["subtask_code"],
        }
    )
    return {"latest_resume": result, "next_action": "evaluate"}


def evaluate_result(state: BridgeState) -> dict:
    result = state["latest_resume"]
    result_ref = result.get("result_ref") or "unknown"
    if result_ref in state.get("processed_resume_ids", []):
        print(f"[evaluate] duplicate resume ignored: result_ref={result_ref}")
        return {"latest_resume": None, "next_action": "wait"}
    decision = accept_or_mark_stale(
        result,
        current_execution_id=state["current_execution_id"],
        current_task_id=state["dispatch_envelope"]["task_id"],
        current_plan_version=state["plan_version"],
        current_subtask_code=state["subtask_code"],
    )
    if not decision["accepted"]:
        print(f"[evaluate] stale ignored: {decision['stale_reason']}")
        return {
            "stale_results": [
                *state.get("stale_results", []),
                result["execution_id"],
            ],
            "processed_resume_ids": [*state.get("processed_resume_ids", []), result_ref],
            "latest_resume": None,
            "next_action": "wait",
        }
    print(f"[evaluate] accepted: execution_id={result['execution_id']} result_ref={result_ref}")
    return {
        "accepted_results": [
            *state.get("accepted_results", []),
            result["execution_id"],
        ],
        "processed_resume_ids": [*state.get("processed_resume_ids", []), result_ref],
        "next_action": "finalize",
    }


def finalize(state: BridgeState) -> dict:
    payload = state["latest_resume"]["result_payload"]
    return {
        "final_result": (
            f"accepted={state.get('accepted_results', [])} "
            f"stale={state.get('stale_results', [])} "
            f"summary={payload['summary']}"
        )
    }


def route(state: BridgeState) -> Literal["wait", "evaluate", "finalize"]:
    return state.get("next_action", "finalize")


async def main() -> None:
    checkpoint_mgr = CheckpointManager()
    checkpointer = await checkpoint_mgr.get_checkpointer()
    require_real_redis(
        backend=checkpoint_mgr.backend,
        degraded=checkpoint_mgr.degraded,
        last_error=checkpoint_mgr.last_error,
    )

    graph = StateGraph(BridgeState)
    graph.add_node("dispatch", dispatch)
    graph.add_node("wait", wait_for_result)
    graph.add_node("evaluate", evaluate_result)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", route)
    graph.add_conditional_edges("wait", route)
    graph.add_conditional_edges("evaluate", route)
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=checkpointer)

    thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("bridge")
    config = {"configurable": {"thread_id": thread_id}}

    print("=== 第一次调用：只分发并进入等待态 ===")
    waiting = await app.ainvoke(
        {
            "task_id": "task-001",
            "plan_version": 1,
            "subtask_code": "ST-001",
            "query": "分析近 30 天的差旅制度变化",
            "thread_id": thread_id,
            "accepted_results": [],
            "stale_results": [],
            "processed_resume_ids": [],
        },
        config=config,
    )
    print(f"waiting_snapshot={waiting}\n")

    print("\n=== 旧结果回写：不会推进 finalize ===")
    stale_waiting = await app.ainvoke(
        Command(
            resume={
                "thread_id": thread_id,
                "execution_id": "exec-stale-old",
                "task_id": "task-stale",
                "status": "COMPLETED",
                "result_ref": "run://2999",
                "result_payload": {
                    "summary": "旧 worker 结果",
                    "plan_version": 0,
                    "subtask_code": "ST-OLD",
                },
            }
        ),
        config=config,
    )
    print(f"after_stale_snapshot={stale_waiting}\n")

    print("\n=== 重复回放同一 stale result：不会再次写 accepted/stale ===")
    duplicate = await app.ainvoke(
        Command(
            resume={
                "thread_id": thread_id,
                "execution_id": "exec-stale-old",
                "task_id": "task-stale",
                "status": "COMPLETED",
                "result_ref": "run://2999",
                "result_payload": {
                    "summary": "旧 worker 结果",
                    "plan_version": 0,
                    "subtask_code": "ST-OLD",
                },
            }
        ),
        config=config,
    )
    print(f"after_duplicate_snapshot={duplicate}\n")

    print("\n=== 当前结果回写：accepted 后完成 ===")
    completed = await app.ainvoke(
        Command(
            resume={
                "thread_id": thread_id,
                "execution_id": waiting["current_execution_id"],
                "task_id": waiting["dispatch_envelope"]["task_id"],
                "status": "COMPLETED",
                "result_ref": "run://3001",
                "result_payload": {
                    "summary": "worker 已完成 evidence merge",
                    "plan_version": waiting["plan_version"],
                    "subtask_code": waiting["subtask_code"],
                },
            }
        ),
        config=config,
    )
    print(f"completed_snapshot={completed}")
    print(completed["final_result"])

    await checkpoint_mgr.aclose()


if __name__ == "__main__":
    asyncio.run(main())
