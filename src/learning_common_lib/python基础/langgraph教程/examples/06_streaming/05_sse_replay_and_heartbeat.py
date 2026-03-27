from __future__ import annotations

"""
目标：演示生产级 SSE 的 replay + heartbeat 语义。
关键 API：事件持久化、Last-Event-ID、heartbeat
运行命令：python 05_sse_replay_and_heartbeat.py
预期现象：
  1. 图执行时先写结构化事件
  2. 第一次连接能收到完整事件流
  3. 断线后带 Last-Event-ID 重新连接，只回放未消费事件
  4. 没有新业务事件时仍发送 heartbeat
生产提醒：
  - replay 依赖持久化事件，不依赖内存 token 流
  - SSE 的 `id` 应该是单调递增事件 ID，而不是随机 UUID
"""

import asyncio
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


EVENT_LOG: list[dict] = []
NEXT_EVENT_ID = 1


class ProgressState(TypedDict, total=False):
    request_id: str
    query: str
    status: str


def append_event(request_id: str, event: str, data: dict) -> dict:
    global NEXT_EVENT_ID
    record = {
        "id": NEXT_EVENT_ID,
        "event": event,
        "data": {"request_id": request_id, **data},
    }
    EVENT_LOG.append(record)
    NEXT_EVENT_ID += 1
    return record


def accept(state: ProgressState) -> dict:
    append_event(state["request_id"], "task.accepted", {"status": "PENDING"})
    return {"status": "PLANNING"}


def plan(state: ProgressState) -> dict:
    append_event(state["request_id"], "task.planning", {"status": "PLANNING"})
    return {"status": "EXECUTING"}


def complete(state: ProgressState) -> dict:
    append_event(
        state["request_id"],
        "task.completed",
        {"status": "COMPLETED", "answer": f"已完成查询：{state.get('query', '')}"},
    )
    return {"status": "COMPLETED"}


def to_sse(record: dict) -> str:
    return (
        f"id: {record['id']}\n"
        f"event: {record['event']}\n"
        f"data: {json.dumps(record['data'], ensure_ascii=False)}\n\n"
    )


async def stream_events(*, request_id: str, last_event_id: int | None = None):
    records = [
        record for record in EVENT_LOG
        if record["data"].get("request_id") == request_id
    ]
    replay = (
        records
        if last_event_id is None
        else [record for record in records if record["id"] > last_event_id]
    )
    if replay:
        print(
            f"[replay] request_id={request_id} "
            f"last_event_id={last_event_id} "
            f"available_ids={[item['id'] for item in records]} "
            f"replayed_ids={[item['id'] for item in replay]}"
        )
        for record in replay:
            yield to_sse(record)
            await asyncio.sleep(0.01)
    else:
        heartbeat = {
            "id": last_event_id or 0,
            "event": "heartbeat",
            "data": {"request_id": request_id, "ts": "2026-03-26T12:00:00Z"},
        }
        yield to_sse(heartbeat)


async def main() -> None:
    EVENT_LOG.clear()
    global NEXT_EVENT_ID
    NEXT_EVENT_ID = 1

    graph = StateGraph(ProgressState)
    graph.add_node("accept", accept)
    graph.add_node("plan", plan)
    graph.add_node("complete", complete)
    graph.add_edge(START, "accept")
    graph.add_edge("accept", "plan")
    graph.add_edge("plan", "complete")
    graph.add_edge("complete", END)
    app = graph.compile()

    await app.ainvoke({"request_id": "req-sse-001", "query": "整理差旅规则变化"})

    print("=== 第一次连接：完整事件流 ===")
    async for sse in stream_events(request_id="req-sse-001"):
        print(sse.strip())

    print("\n=== 断线重连：只回放未消费事件 ===")
    async for sse in stream_events(request_id="req-sse-001", last_event_id=2):
        print(sse.strip())

    print("\n=== 无新事件时：仍然发送 heartbeat ===")
    async for sse in stream_events(request_id="req-sse-001", last_event_id=3):
        print(sse.strip())


if __name__ == "__main__":
    asyncio.run(main())
