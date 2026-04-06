"""
Double-texting 处理策略（更真实的等待/恢复版）。

目标:
    演示同一 thread_id 上，用户在任务等待阶段再次发送消息时的处理策略：
    enqueue / reject / interrupt / rollback / idempotency。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/15_production_deployment/03_double_texting.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/15_production_deployment/03_double_texting.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    - 本例是“单进程网关 + 图等待态”示例，不代表多实例网关实现
    - 真正生产环境还需要共享幂等缓存、分布式锁或统一入口层策略
    - `interrupt` / `rollback` 在这里表示“用新请求替换同一 thread 的当前头”
    - 因此 worker 回写结果时必须携带 request_id，并在 resume 前做 fencing
    - 如果你想保留被替换请求的历史头，应该新开 thread_id，而不是覆盖当前线程
"""
from __future__ import annotations

import asyncio
from collections import deque
from enum import Enum
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class Strategy(str, Enum):
    """ 处理策略 """
    ENQUEUE = "enqueue"
    REJECT = "reject"
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"


class ChatState(TypedDict, total=False):
    """ 聊天状态 """
    request_id: str                    # 请求 ID
    incoming_message: str               # 输入消息
    waiting_reason: str                 # 等待原因
    worker_summary: str                 # 总结
    final_answer: str                   # 最终答案


REQUEST_COUNTER = 0                  # 请求计数器


def next_request_id() -> str:
    """ 获取下一个请求 ID """
    global REQUEST_COUNTER
    REQUEST_COUNTER += 1
    return f"req-{REQUEST_COUNTER:03d}"


def start_request(state: ChatState) -> dict:
    """ 开始处理请求 """
    request_id = next_request_id()
    print(f"[graph] 开始处理 {request_id}: {state['incoming_message']}")
    return {"request_id": request_id, "waiting_reason": "WORKER", "final_answer": ""}


def wait_for_worker(state: ChatState) -> dict:
    """ 等待工人处理请求 """
    payload = interrupt(
        {
            "request_id": state["request_id"],
            "waiting_reason": state["waiting_reason"],
            "message": state["incoming_message"],
        }
    )
    return {"worker_summary": payload["worker_summary"], "waiting_reason": "NONE"}


def finalize(state: ChatState) -> dict:
    """ 完成请求 """
    return {
        "final_answer": (
            f"{state['request_id']} 完成："
            f"{state['incoming_message']} -> {state['worker_summary']}"
        )
    }


class DoubleTextGateway:
    """网关层策略：检查同一 thread_id 是否已有等待中的任务。"""

    def __init__(self, app) -> None:
        self.app = app                                             # 图实例
        self.queues: dict[str, deque[tuple[str, str]]] = {}
        self.idempotency_cache: dict[str, dict] = {}                # 幂等缓存
        self.cancelled_requests: dict[str, list[str]] = {}          # 取消请求记录
        self.stale_worker_results: dict[str, list[str]] = {}        # 过时结果

    async def _is_waiting(self, thread_id: str) -> bool:
        """ 检查线程是否在 """
        state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        return bool(state.values) and state.values.get("waiting_reason") == "WORKER"

    async def _current_request_id(self, thread_id: str) -> str | None:
        """ 获取当前请求 ID """
        state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("request_id") if state.values else None

    async def _start_new(self, thread_id: str, message: str, idempotency_key: str) -> dict:
        """ 启动新请求 """
        result = await self.app.ainvoke(
            {"incoming_message": message},
            config={"configurable": {"thread_id": thread_id}},
        )
        response = {
            "status": "waiting",
            "thread_id": thread_id,
            "request_id": result["request_id"],
            "waiting_reason": result["waiting_reason"],
        }
        self.idempotency_cache[idempotency_key] = response
        return response

    async def submit(
        self,
        *,
        thread_id: str,
        message: str,
        strategy: Strategy,
        idempotency_key: str,
    ) -> dict:
        """ 提交请求 """
        if idempotency_key in self.idempotency_cache:                    # 幂等缓存命中
            cached = self.idempotency_cache[idempotency_key]
            print(f"[gateway] idempotency hit key={idempotency_key} cached={cached}")
            return {**cached, "status": "idempotent_replay"}

        if not await self._is_waiting(thread_id):
            """ 当前无任务，直接启动 """
            print(f"[gateway] thread_id={thread_id} 当前无等待任务，直接启动")
            return await self._start_new(thread_id, message, idempotency_key)

        current_request_id = await self._current_request_id(thread_id)    # 当前请求 ID
        print(
            f"[gateway] thread_id={thread_id} active_request_id={current_request_id} "
            f"strategy={strategy.value}"
        )
        if strategy == Strategy.REJECT:                                # 拒绝策略
            response = {
                "status": "rejected_busy",
                "thread_id": thread_id,
                "active_request_id": current_request_id,
            }
            self.idempotency_cache[idempotency_key] = response
            return response

        if strategy == Strategy.ENQUEUE:                              # 入队策略
            self.queues.setdefault(thread_id, deque()).append((message, idempotency_key))
            print(f"[gateway] queue[{thread_id}]={list(self.queues[thread_id])}")
            response = {
                "status": "enqueued",
                "thread_id": thread_id,
                "active_request_id": current_request_id,
                "queue_size": len(self.queues[thread_id]),
            }
            self.idempotency_cache[idempotency_key] = response
            return response

        if strategy == Strategy.INTERRUPT:                             # 中断策略
            self.cancelled_requests.setdefault(thread_id, []).append(current_request_id or "unknown")
            print(f"[gateway] interrupt cancel record={self.cancelled_requests[thread_id]}")
            return await self._start_new(thread_id, message, idempotency_key)

        if strategy == Strategy.ROLLBACK:                              # 回滚策略
            self.cancelled_requests.setdefault(thread_id, []).append(f"rollback:{current_request_id or 'unknown'}")
            self.queues[thread_id] = deque()
            print(f"[gateway] rollback cancel record={self.cancelled_requests[thread_id]}")
            return await self._start_new(thread_id, message, idempotency_key)

        raise ValueError(f"未知策略: {strategy}")

    async def resume_worker(
        self,
        *,
        thread_id: str,
        request_id: str,
        worker_summary: str,
    ) -> dict:
        current_state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        print(f"[gateway.resume] before_state={current_state.values}")
        active_request_id = current_state.values.get("request_id") if current_state.values else None
        waiting_reason = current_state.values.get("waiting_reason") if current_state.values else None

        if waiting_reason != "WORKER":
            print(
                f"[gateway.resume] ignore because thread is not waiting: "
                f"thread_id={thread_id} active_request_id={active_request_id}"
            )
            return {
                "status": "not_waiting",
                "thread_id": thread_id,
                "request_id": request_id,
                "active_request_id": active_request_id,
            }

        if request_id != active_request_id:
            self.stale_worker_results.setdefault(thread_id, []).append(request_id)
            print(
                f"[gateway.resume] stale worker result ignored: "
                f"request_id={request_id} active_request_id={active_request_id}"
            )
            return {
                "status": "stale_ignored",
                "thread_id": thread_id,
                "request_id": request_id,
                "active_request_id": active_request_id,
            }

        result = await self.app.ainvoke(
            Command(resume={"request_id": request_id, "worker_summary": worker_summary}),
            config={"configurable": {"thread_id": thread_id}},
        )
        print(f"[gateway.resume] completed_result={result}")
        if self.queues.get(thread_id):
            message, idem_key = self.queues[thread_id].popleft()
            print(f"[gateway.resume] dequeue next message={message} remaining_queue={list(self.queues[thread_id])}")
            queued = await self._start_new(thread_id, message, idem_key)
            return {
                "completed": result["final_answer"],
                "next_queued": queued,
            }
        return {"completed": result["final_answer"], "next_queued": None}


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(ChatState)
    graph.add_node("start", start_request)
    graph.add_node("wait", wait_for_worker)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "start")
    graph.add_edge("start", "wait")
    graph.add_edge("wait", "finalize")
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=saver)
    gateway = DoubleTextGateway(app)

    thread_id = "chat-thread-001"
    print("=== 第一次消息：进入等待态 ===")
    first_wait = await gateway.submit(
        thread_id=thread_id,
        message="整理公司的差旅规则变化",
        strategy=Strategy.ENQUEUE,
        idempotency_key="idem-001",
    )
    print(f"first_wait: {first_wait}")

    print("\n=== 同线程再次发送：reject ===")
    print("submit:")
    print(
        await gateway.submit(
            thread_id=thread_id,
            message="顺便整理报销规则",
            strategy=Strategy.REJECT,
            idempotency_key="idem-002",
        )
    )

    print("\n=== 同线程再次发送：enqueue ===")
    print("submit:")
    print(
        await gateway.submit(
            thread_id=thread_id,
            message="再补一份近 30 天版本",
            strategy=Strategy.ENQUEUE,
            idempotency_key="idem-003",
        )
    )

    print("\n=== worker 完成当前请求 ===")
    print("resume_worker:")
    print(
        await gateway.resume_worker(
            thread_id=thread_id,
            request_id=first_wait["request_id"],
            worker_summary="已收集 2 条制度变化",
        )
    )

    print("\n=== 新线程演示 interrupt ===")
    interrupt_thread = "chat-thread-002"
    interrupted_wait = await gateway.submit(
        thread_id=interrupt_thread,
        message="先整理全部差旅制度",
        strategy=Strategy.ENQUEUE,
        idempotency_key="idem-010",
    )
    replaced_wait = await gateway.submit(
        thread_id=interrupt_thread,
        message="不用全部了，只看近 30 天",
        strategy=Strategy.INTERRUPT,
        idempotency_key="idem-011",
    )
    print(
        replaced_wait
    )

    print("\n=== 旧 worker 结果回写：会被 request_id fencing 忽略 ===")
    print("resume_worker:")
    print(
        await gateway.resume_worker(
            thread_id=interrupt_thread,
            request_id=interrupted_wait["request_id"],
            worker_summary="这是旧请求的结果，不应污染新请求",
        )
    )

    print("\n=== 新请求 worker 完成 ===")
    print("resume_worker:")
    print(
        await gateway.resume_worker(
            thread_id=interrupt_thread,
            request_id=replaced_wait["request_id"],
            worker_summary="已整理近 30 天范围的制度变化",
        )
    )

    print("\n=== 重复提交同一个 idempotency key ===")
    print("submit:")
    print(
        await gateway.submit(
            thread_id=interrupt_thread,
            message="不用全部了，只看近 30 天",
            strategy=Strategy.INTERRUPT,
            idempotency_key="idem-011",
        )
    )

    print("\n取消记录:")
    print(gateway.cancelled_requests)
    print("stale worker 记录:")
    print(gateway.stale_worker_results)


if __name__ == "__main__":
    asyncio.run(main())
