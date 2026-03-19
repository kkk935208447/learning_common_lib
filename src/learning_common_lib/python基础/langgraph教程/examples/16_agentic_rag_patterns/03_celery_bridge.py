"""LangGraph + Celery 桥接模式。

目标：
    演示 LangGraph 与 Celery 的桥接模式：
    LangGraph 负责编排，Celery 负责异步任务执行，
    通过“分发 -> 等待 -> 外部回写 -> 恢复”实现解耦。

关键 API：
    - asyncio.to_thread(task.delay) —— 异步提交 Celery 任务
    - interrupt(...) —— 图进入等待态
    - Command(resume=...) —— 外部结果到达后恢复图执行

运行命令：
    python 03_celery_bridge.py

预期现象：
    1. 第一次调用只负责分发任务并进入等待态
    2. 模拟 Celery worker 将结果写回图状态
    3. 第二次调用恢复图执行，完成结果聚合

生产提醒：
    - 图节点内绝不 `.get()` 等待 Celery 结果
    - 真正的结果载荷应由外部存储或回调写入，不要塞进图内长时间阻塞等待
    - 本示例用 MemorySaver + interrupt 演示控制流骨架
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt


# ══════════════════════════════════════════════════════════
# Mock Celery
# ══════════════════════════════════════════════════════════

class MockAsyncResult:
    """模拟 Celery AsyncResult。"""

    def __init__(self, task_id: str, result: dict | None = None):
        self.id = task_id
        self._result = result
        self.status = "PENDING"

    def get(self, timeout: float = 10.0) -> dict:
        """演示用阻塞接口，真实图节点中禁止调用。"""
        time.sleep(min(timeout, 0.1))
        self.status = "SUCCESS"
        return self._result or {"status": "done"}


class MockCeleryTask:
    """模拟 Celery Task。"""

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


# ══════════════════════════════════════════════════════════
# LangGraph 图定义
# ══════════════════════════════════════════════════════════

class BridgeState(TypedDict, total=False):
    query: str
    celery_task_ids: list[str]
    celery_results: list[dict]
    waiting_reason: str
    final_result: str
    status: str


def dispatch_to_celery(state: BridgeState) -> dict:
    """分发任务到 Celery，只返回 task_id。"""
    query = state["query"]
    print(f"[dispatch] 分发任务到 Celery: {query}")

    result1 = heavy_task.delay(query)
    result2 = api_task.delay(query)
    task_ids = [result1.id, result2.id]

    print(f"[dispatch] 已提交 {len(task_ids)} 个 Celery 任务")
    return {
        "celery_task_ids": task_ids,
        "waiting_reason": "celery_results",
        "status": "waiting_celery",
    }


def wait_for_results(state: BridgeState) -> dict:
    """进入等待态，直到外部结果写回后恢复。"""
    if state.get("celery_results"):
        print(f"[wait] 收到外部回写结果 {len(state['celery_results'])} 个，继续执行")
        return {"waiting_reason": "none", "status": "resumed"}

    payload = {
        "waiting_reason": state.get("waiting_reason", "celery_results"),
        "task_ids": state.get("celery_task_ids", []),
    }
    print("[wait] 挂起等待 Celery 回写结果...")
    interrupt(payload)
    return {}


def aggregate_results(state: BridgeState) -> dict:
    """聚合 Celery 结果。"""
    results = state.get("celery_results", [])
    final = f"聚合 {len(results)} 个结果: " + ", ".join(
        sorted(result["task_id"] for result in results)
    )
    print(f"[aggregate] {final}")
    return {"final_result": final, "status": "completed"}


def build_bridge_graph():
    graph = StateGraph(BridgeState)
    graph.add_node("dispatch", dispatch_to_celery)
    graph.add_node("wait", wait_for_results)
    graph.add_node("aggregate", aggregate_results)
    graph.set_entry_point("dispatch")
    graph.add_edge("dispatch", "wait")
    graph.add_edge("wait", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile(checkpointer=MemorySaver())


RESUME_PATTERN = """
resume_orchestrator 模式:

  1. LangGraph 节点提交 Celery 任务后进入等待态
  2. Celery worker 执行完任务后，将结果写回外部存储或 graph state
  3. resume_orchestrator 再次调用图执行（同一 thread_id）恢复流程
  4. 图从等待点继续，读取结果并完成聚合

  关键原则：
  - 图节点里只 dispatch，不等待
  - 结果通过“回写 + 恢复”进入图，不靠同步 .get()
  - 恢复调用必须使用相同的 thread_id
"""


if __name__ == "__main__":
    print("=== LangGraph + Celery 桥接模式 ===\n")

    app = build_bridge_graph()
    config = {"configurable": {"thread_id": "bridge-demo"}}

    print("--- 第一次调用：只分发并进入等待态 ---")
    waiting_state = app.invoke(
        {
            "query": "分析用户行为数据",
            "celery_task_ids": [],
            "celery_results": [],
            "waiting_reason": "none",
            "final_result": "",
            "status": "pending",
        },
        config=config,
    )
    print(f"状态: {waiting_state['status']}")
    print(f"等待原因: {waiting_state['waiting_reason']}")
    print(f"任务 IDs: {waiting_state['celery_task_ids']}")

    print("\n--- 模拟 worker 回写结果并恢复图执行 ---")
    mock_results = [
        {"task_id": task_id, "result": f"result_for_{task_id}"}
        for task_id in waiting_state["celery_task_ids"]
    ]
    app.update_state(config, {"celery_results": mock_results})
    final_state = app.invoke(Command(resume="celery_results_ready"), config=config)

    print(f"\n最终结果: {final_state['final_result']}")
    print(f"状态: {final_state['status']}")
    print(RESUME_PATTERN)
