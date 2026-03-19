"""LangGraph + Celery 桥接模式

目标：
    演示 LangGraph 与 Celery 的桥接模式：
    LangGraph 负责编排，Celery 负责异步任务执行，
    通过 resume_orchestrator 模式实现解耦。

关键 API：
    - asyncio.to_thread(task.delay) —— 异步提交 Celery 任务
    - resume_orchestrator —— Celery 回调触发图恢复
    - 禁止在图节点内 .get()（会阻塞事件循环）

运行命令：
    python 03_celery_bridge.py

预期现象：
    模拟 LangGraph → Celery 任务提交 → 回调恢复的完整流程。
    （不需要真实 Celery broker，使用 mock 演示）

生产提醒：
    - 绝对禁止在 async 图节点内调用 celery_task.get()
    - Celery task 是 async-first 逻辑的薄同步包装
    - 使用 Redis 作为 broker: redis://:123456@localhost:6379/0
    - 任务结果通过回调（而非轮询）传回 LangGraph
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph


# ══════════════════════════════════════════════════════════
# Mock Celery（演示用，不需要真实 Celery 依赖）
# ══════════════════════════════════════════════════════════

class MockAsyncResult:
    """模拟 Celery AsyncResult"""
    def __init__(self, task_id: str, result: dict | None = None):
        self.id = task_id
        self._result = result
        self.status = "PENDING"

    def get(self, timeout: float = 10.0) -> dict:
        """警告：禁止在 async 图节点内调用此方法！"""
        time.sleep(0.1)  # 模拟等待
        self.status = "SUCCESS"
        return self._result or {"status": "done"}


class MockCeleryTask:
    """模拟 Celery Task"""
    def __init__(self, name: str, handler=None):
        self.name = name
        self._handler = handler

    def delay(self, *args, **kwargs) -> MockAsyncResult:
        """提交异步任务"""
        task_id = f"celery-{uuid.uuid4().hex[:8]}"
        print(f"  [Celery] 提交任务 {self.name} (id={task_id})")
        result = self._handler(*args, **kwargs) if self._handler else {"status": "done"}
        return MockAsyncResult(task_id, result)


# ── 模拟 Celery 任务定义 ──────────────────────────────────
# 生产环境:
# celery_app = Celery("myapp", broker="redis://:123456@localhost:6379/0")
#
# @celery_app.task(queue="orchestrate_jobs")
# def resume_orchestrator(result: dict):
#     """Celery task 是 async-first 逻辑的薄同步包装"""
#     return asyncio.run(resume_orchestrator_async(result))

def _do_heavy_computation(data: str) -> dict:
    """模拟耗时计算"""
    time.sleep(0.1)
    return {"computed": f"result_of({data})", "score": 0.92}


def _do_external_api_call(query: str) -> dict:
    """模拟外部 API 调用"""
    time.sleep(0.05)
    return {"api_result": f"external_data_for({query})"}


heavy_task = MockCeleryTask("heavy_computation", _do_heavy_computation)
api_task = MockCeleryTask("external_api_call", _do_external_api_call)


# ══════════════════════════════════════════════════════════
# LangGraph 图定义
# ══════════════════════════════════════════════════════════

class BridgeState(TypedDict):
    query: str
    celery_task_ids: list[str]
    celery_results: list[dict]
    final_result: str
    status: str


def dispatch_to_celery(state: BridgeState) -> dict:
    """将任务分发到 Celery

    关键：使用 asyncio.to_thread 避免阻塞事件循环。
    生产环境中这里只提交任务，不等待结果。
    """
    query = state["query"]
    print(f"[dispatch] 分发任务到 Celery: {query}")

    # 提交多个 Celery 任务
    # 生产环境: await asyncio.to_thread(heavy_task.delay, query)
    result1 = heavy_task.delay(query)
    result2 = api_task.delay(query)

    task_ids = [result1.id, result2.id]
    print(f"[dispatch] 已提交 {len(task_ids)} 个 Celery 任务")

    return {
        "celery_task_ids": task_ids,
        "status": "waiting_celery",
    }


def collect_celery_results(state: BridgeState) -> dict:
    """收集 Celery 任务结果

    生产环境中，这个节点由 resume_orchestrator 回调触发，
    而非主动轮询。这里为演示简化为同步收集。
    """
    task_ids = state["celery_task_ids"]
    print(f"[collect] 收集 {len(task_ids)} 个 Celery 任务结果")

    # 模拟收集结果（生产环境通过回调获取）
    results = [
        {"task_id": tid, "result": f"result_for_{tid}"}
        for tid in task_ids
    ]
    print(f"[collect] 收集完成: {len(results)} 个结果")

    return {"celery_results": results, "status": "collected"}


def aggregate_results(state: BridgeState) -> dict:
    """聚合 Celery 结果"""
    results = state["celery_results"]
    final = f"聚合 {len(results)} 个结果: " + ", ".join(
        r["task_id"] for r in results
    )
    print(f"[aggregate] {final}")
    return {"final_result": final, "status": "completed"}


def build_bridge_graph():
    graph = StateGraph(BridgeState)
    graph.add_node("dispatch", dispatch_to_celery)
    graph.add_node("collect", collect_celery_results)
    graph.add_node("aggregate", aggregate_results)
    graph.set_entry_point("dispatch")
    graph.add_edge("dispatch", "collect")
    graph.add_edge("collect", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


# ══════════════════════════════════════════════════════════
# resume_orchestrator 模式说明
# ══════════════════════════════════════════════════════════

RESUME_PATTERN = """
resume_orchestrator 模式:

  1. LangGraph 节点提交 Celery 任务后，图暂停（interrupt）
  2. Celery worker 执行完任务后，调用 resume_orchestrator
  3. resume_orchestrator 是一个 Celery task，它：
     - 将结果写入 checkpoint
     - 恢复 LangGraph 图的执行
  4. 图从断点继续，读取 Celery 结果并继续处理

  关键原则：
  - Celery task 是 async-first 逻辑的薄同步包装
  - 禁止在图节点内调用 .get()（阻塞事件循环）
  - 使用回调而非轮询获取结果
"""


if __name__ == "__main__":
    print("=== LangGraph + Celery 桥接模式 ===\n")

    app = build_bridge_graph()
    result = app.invoke({
        "query": "分析用户行为数据",
        "celery_task_ids": [],
        "celery_results": [],
        "final_result": "",
        "status": "pending",
    })

    print(f"\n最终结果: {result['final_result']}")
    print(f"状态: {result['status']}")
    print(RESUME_PATTERN)
