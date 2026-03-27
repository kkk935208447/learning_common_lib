"""Double-texting 处理策略（更真实的等待/恢复版）。

目标：
    演示同一 thread_id 上，用户在任务等待阶段再次发送消息时的处理策略：
    enqueue / reject / interrupt / rollback / idempotency。

运行命令：
    python 03_double_texting.py

生产提醒：
    - 本例是“单进程网关 + 图等待态”示例，不代表多实例网关实现
    - 真正生产环境还需要共享幂等缓存、分布式锁或统一入口层策略
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
    ENQUEUE = "enqueue"
    REJECT = "reject"
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"


class ChatState(TypedDict, total=False):
    request_id: str
    incoming_message: str
    waiting_reason: str
    worker_summary: str
    final_answer: str


REQUEST_COUNTER = 0


def next_request_id() -> str:
    global REQUEST_COUNTER
    REQUEST_COUNTER += 1
    return f"req-{REQUEST_COUNTER:03d}"


def start_request(state: ChatState) -> dict:
    request_id = next_request_id()
    print(f"[graph] 开始处理 {request_id}: {state['incoming_message']}")
    return {"request_id": request_id, "waiting_reason": "WORKER", "final_answer": ""}


def wait_for_worker(state: ChatState) -> dict:
    payload = interrupt(
        {
            "request_id": state["request_id"],
            "waiting_reason": state["waiting_reason"],
            "message": state["incoming_message"],
        }
    )
    return {"worker_summary": payload["worker_summary"], "waiting_reason": "NONE"}


def finalize(state: ChatState) -> dict:
    return {
        "final_answer": (
            f"{state['request_id']} 完成："
            f"{state['incoming_message']} -> {state['worker_summary']}"
        )
    }


class DoubleTextGateway:
    """网关层策略：检查同一 thread_id 是否已有等待中的任务。"""

    def __init__(self, app) -> None:
        self.app = app
        self.queues: dict[str, deque[tuple[str, str]]] = {}
        self.idempotency_cache: dict[str, dict] = {}
        self.cancelled_requests: dict[str, list[str]] = {}

    async def _is_waiting(self, thread_id: str) -> bool:
        state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        return bool(state.values) and state.values.get("waiting_reason") == "WORKER"

    async def _current_request_id(self, thread_id: str) -> str | None:
        state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("request_id") if state.values else None

    async def _start_new(self, thread_id: str, message: str, idempotency_key: str) -> dict:
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
        if idempotency_key in self.idempotency_cache:
            cached = self.idempotency_cache[idempotency_key]
            print(f"[gateway] idempotency hit key={idempotency_key} cached={cached}")
            return {**cached, "status": "idempotent_replay"}

        if not await self._is_waiting(thread_id):
            print(f"[gateway] thread_id={thread_id} 当前无等待任务，直接启动")
            return await self._start_new(thread_id, message, idempotency_key)

        current_request_id = await self._current_request_id(thread_id)
        print(
            f"[gateway] thread_id={thread_id} active_request_id={current_request_id} "
            f"strategy={strategy.value}"
        )
        if strategy == Strategy.REJECT:
            response = {
                "status": "rejected_busy",
                "thread_id": thread_id,
                "active_request_id": current_request_id,
            }
            self.idempotency_cache[idempotency_key] = response
            return response

        if strategy == Strategy.ENQUEUE:
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

        if strategy == Strategy.INTERRUPT:
            self.cancelled_requests.setdefault(thread_id, []).append(current_request_id or "unknown")
            print(f"[gateway] interrupt cancel record={self.cancelled_requests[thread_id]}")
            return await self._start_new(thread_id, message, idempotency_key)

        if strategy == Strategy.ROLLBACK:
            self.cancelled_requests.setdefault(thread_id, []).append(f"rollback:{current_request_id or 'unknown'}")
            self.queues[thread_id] = deque()
            print(f"[gateway] rollback cancel record={self.cancelled_requests[thread_id]}")
            return await self._start_new(thread_id, message, idempotency_key)

        raise ValueError(f"未知策略: {strategy}")

    async def resume_worker(self, *, thread_id: str, worker_summary: str) -> dict:
        current_state = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        print(f"[gateway.resume] before_state={current_state.values}")
        result = await self.app.ainvoke(
            Command(resume={"worker_summary": worker_summary}),
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
    print(
        await gateway.submit(
            thread_id=thread_id,
            message="整理公司的差旅规则变化",
            strategy=Strategy.ENQUEUE,
            idempotency_key="idem-001",
        )
    )

    print("\n=== 同线程再次发送：reject ===")
    print(
        await gateway.submit(
            thread_id=thread_id,
            message="顺便整理报销规则",
            strategy=Strategy.REJECT,
            idempotency_key="idem-002",
        )
    )

    print("\n=== 同线程再次发送：enqueue ===")
    print(
        await gateway.submit(
            thread_id=thread_id,
            message="再补一份近 30 天版本",
            strategy=Strategy.ENQUEUE,
            idempotency_key="idem-003",
        )
    )

    print("\n=== worker 完成当前请求 ===")
    print(
        await gateway.resume_worker(
            thread_id=thread_id,
            worker_summary="已收集 2 条制度变化",
        )
    )

    print("\n=== 新线程演示 interrupt ===")
    interrupt_thread = "chat-thread-002"
    await gateway.submit(
        thread_id=interrupt_thread,
        message="先整理全部差旅制度",
        strategy=Strategy.ENQUEUE,
        idempotency_key="idem-010",
    )
    print(
        await gateway.submit(
            thread_id=interrupt_thread,
            message="不用全部了，只看近 30 天",
            strategy=Strategy.INTERRUPT,
            idempotency_key="idem-011",
        )
    )

    print("\n=== 重复提交同一个 idempotency key ===")
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


if __name__ == "__main__":
    asyncio.run(main())
