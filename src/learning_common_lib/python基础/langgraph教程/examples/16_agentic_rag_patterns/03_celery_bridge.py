"""LangGraph + Celery 桥接模式。

目标：
    演示 LangGraph 与 Celery 的桥接模式：
    LangGraph 负责编排，Celery 负责异步任务执行，
    通过“分发 -> 等待 -> 外部回写 -> 恢复”实现解耦。

关键 API：
    - asyncio.to_thread(task.delay) —— 异步提交 Celery 任务
    - interrupt(...) —— 图进入等待态
    - Command(resume=...) —— 外部结果到达后恢复图执行

生产提醒：
    - 本示例用 Mock Celery 演示控制流
    - checkpoint 运行时默认采用 Redis-first
    - payload 中显式携带 thread_id / execution_id / task_id 契约
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

try:
    from ...templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
    )
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
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


class MockAsyncResult:
    def __init__(self, task_id: str, result: dict | None = None):
        self.id = task_id
        self._result = result
        self.status = "PENDING"

    def get(self, timeout: float = 10.0) -> dict:
        time.sleep(min(timeout, 0.1))
        self.status = "SUCCESS"
        return self._result or {"status": "done"}


class MockCeleryTask:
    def __init__(self, name: str, handler=None):
        self.name = name
        self._handler = handler

    def delay(self, *args, **kwargs) -> MockAsyncResult:
        task_id = f"celery-{uuid.uuid4().hex[:8]}"
        print(f"  [Celery] 提交任务 {self.name} (id={task_id})")
        result = self._handler(*args, **kwargs) if self._handler else {"status": "done"}
        return MockAsyncResult(task_id, result)


def _do_heavy_computation(data: str) -> dict:
    time.sleep(0.05)
    return {"computed": f"result_of({data})", "score": 0.92}


def _do_external_api_call(query: str) -> dict:
    time.sleep(0.05)
    return {"api_result": f"external_data_for({query})"}


heavy_task = MockCeleryTask("heavy_computation", _do_heavy_computation)
api_task = MockCeleryTask("external_api_call", _do_external_api_call)


class BridgeState(TypedDict, total=False):
    query: str
    thread_id: str
    celery_task_ids: list[str]
    dispatch_envelopes: list[dict]
    celery_results: list[dict]
    execution_id: str
    waiting_reason: str
    final_result: str
    status: str


def dispatch_to_celery(state: BridgeState) -> dict:
    query = state["query"]
    thread_id = state["thread_id"]
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    print(f"[dispatch] 分发任务到 Celery: {query}")

    result1 = heavy_task.delay(query)
    result2 = api_task.delay(query)
    task_ids = [result1.id, result2.id]
    dispatch_envelopes = [
        {
            "task_id": result1.id,
            "task_name": heavy_task.name,
            "thread_id": thread_id,
            "execution_id": execution_id,
        },
        {
            "task_id": result2.id,
            "task_name": api_task.name,
            "thread_id": thread_id,
            "execution_id": execution_id,
        },
    ]

    print(f"[dispatch] 已提交 {len(task_ids)} 个 Celery 任务")
    return {
        "thread_id": thread_id,
        "celery_task_ids": task_ids,
        "dispatch_envelopes": dispatch_envelopes,
        "execution_id": execution_id,
        "waiting_reason": "celery_results",
        "status": "waiting_celery",
    }


def wait_for_results(state: BridgeState) -> dict:
    results = state.get("celery_results", [])
    if results:
        execution_id = state.get("execution_id", "")
        thread_id = state.get("thread_id", "")
        task_ids = set(state.get("celery_task_ids", []))
        invalid_results = [
            result
            for result in results
            if result.get("execution_id") != execution_id
            or result.get("thread_id") != thread_id
            or result.get("task_id") not in task_ids
        ]
        if invalid_results:
            raise ValueError(f"收到不属于当前执行的 Celery 结果: {invalid_results}")
        print(f"[wait] 收到外部回写结果 {len(state['celery_results'])} 个，继续执行")
        return {"waiting_reason": "none", "status": "resumed"}

    payload = {
        "waiting_reason": state.get("waiting_reason", "celery_results"),
        "thread_id": state.get("thread_id", ""),
        "execution_id": state.get("execution_id", ""),
        "task_ids": state.get("celery_task_ids", []),
    }
    print("[wait] 挂起等待 Celery 回写结果...")
    interrupt(payload)
    return {}


def aggregate_results(state: BridgeState) -> dict:
    results = state.get("celery_results", [])
    final = f"聚合 {len(results)} 个结果: " + ", ".join(sorted(result["task_id"] for result in results))
    print(f"[aggregate] {final}")
    return {"final_result": final, "status": "completed"}


def build_bridge_graph(checkpointer):
    graph = StateGraph(BridgeState)
    graph.add_node("dispatch", dispatch_to_celery)
    graph.add_node("wait", wait_for_results)
    graph.add_node("aggregate", aggregate_results)
    graph.set_entry_point("dispatch")
    graph.add_edge("dispatch", "wait")
    graph.add_edge("wait", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile(checkpointer=checkpointer)


RESUME_PATTERN = """
resume_orchestrator 模式:

  1. LangGraph 节点提交 Celery 任务后进入等待态
  2. Celery worker 执行完任务后，将结果写回外部存储或 graph state
  3. resume_orchestrator 再次调用图执行（同一 thread_id）恢复流程
  4. 图从等待点继续，读取结果并完成聚合

  关键原则：
  - 图节点里只 dispatch，不等待
  - 结果通过“回写 + 恢复”进入图，不靠同步 .get()
  - payload 中应显式携带 thread_id / execution_id / task_id
"""


if __name__ == "__main__":
    async def main() -> None:
        print("=== LangGraph + Celery 桥接模式 ===\n")

        checkpoint_mgr = CheckpointManager()
        checkpointer = await checkpoint_mgr.get_checkpointer()
        app = build_bridge_graph(checkpointer)
        thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("bridge")
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        require_real_redis(
            backend=checkpoint_mgr.backend,
            degraded=checkpoint_mgr.degraded,
            last_error=checkpoint_mgr.last_error,
        )

        print("--- 第一次调用：只分发并进入等待态 ---")
        print(
            f"checkpoint_backend={checkpoint_mgr.backend} "
            f"checkpoint_degraded={checkpoint_mgr.degraded} "
            f"last_error={checkpoint_mgr.last_error}"
        )
        waiting_state = await app.ainvoke(
            {
                "query": "分析用户行为数据",
                "thread_id": thread_id,
                "celery_task_ids": [],
                "dispatch_envelopes": [],
                "celery_results": [],
                "execution_id": "",
                "waiting_reason": "none",
                "final_result": "",
                "status": "pending",
            },
            config=config,
        )
        print(f"状态: {waiting_state['status']}")
        print(f"thread_id: {waiting_state['thread_id']}")
        print(f"执行 ID: {waiting_state['execution_id']}")
        print(f"等待原因: {waiting_state['waiting_reason']}")
        print(f"任务 IDs: {waiting_state['celery_task_ids']}")

        print("\n--- 模拟 worker 回写结果并恢复图执行 ---")
        mock_results = [
            {
                "task_id": task_id,
                "thread_id": waiting_state["thread_id"],
                "execution_id": waiting_state["execution_id"],
                "result": f"result_for_{task_id}",
            }
            for task_id in waiting_state["celery_task_ids"]
        ]
        await app.aupdate_state(config, {"celery_results": mock_results})
        final_state = await app.ainvoke(Command(resume="celery_results_ready"), config=config)

        print(f"\n最终结果: {final_state['final_result']}")
        print(f"状态: {final_state['status']}")
        print(RESUME_PATTERN)

        await checkpoint_mgr.aclose()

    asyncio.run(main())
