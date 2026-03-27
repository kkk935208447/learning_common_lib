"""
06_streaming / 07_store_backed_event_replay

目标:
    演示 store-backed progress events，建立“可 replay 真理源”的心智。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    InMemoryStore / aput / asearch

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/06_streaming/07_store_backed_event_replay.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/06_streaming/07_store_backed_event_replay.py

预期现象:
    1. 结构化 progress event 写入 store
    2. `Last-Event-ID` 只回放未消费的业务事件
    3. token 流不会被持久化，也不会被 replay

生产提醒:
    - token stream 只适合 UI 即时渲染
    - replay 真理源必须是结构化事件或事件表
    - 本例用 InMemoryStore 演示接口，生产环境可替换为 RedisStore/DB 事件表
"""
from __future__ import annotations

import asyncio
import json

from langgraph.store.memory import InMemoryStore


def event_namespace(thread_id: str) -> tuple[str, ...]:
    return ("threads", thread_id, "events")


async def next_event_id(store: InMemoryStore, thread_id: str) -> int:
    ns = event_namespace(thread_id)
    meta = await store.aget(ns, "__meta__")
    current = 1 if meta is None else int(meta.value.get("last_event_id", 0)) + 1
    await store.aput(ns, "__meta__", {"last_event_id": current})
    return current


async def append_progress_event(store: InMemoryStore, thread_id: str, event: str, data: dict) -> dict:
    record = {
        "id": await next_event_id(store, thread_id),
        "event": event,
        "data": {"thread_id": thread_id, **data},
    }
    await store.aput(event_namespace(thread_id), f"{record['id']:08d}", record)
    print(f"[append] persisted_event id={record['id']} event={event}")
    return record


async def replay_progress_events(store: InMemoryStore, thread_id: str, last_event_id: int | None) -> list[dict]:
    items = await store.asearch(event_namespace(thread_id), limit=100)
    records = [item.value for item in items if item.key != "__meta__"]
    records.sort(key=lambda item: item["id"])
    if last_event_id is None:
        replay = records
    else:
        replay = [item for item in records if item["id"] > last_event_id]
    print(
        f"[replay] last_event_id={last_event_id} "
        f"available_ids={[item['id'] for item in records]} "
        f"replayed_ids={[item['id'] for item in replay]}"
    )
    return replay


def format_event(record: dict) -> str:
    return (
        f"id: {record['id']}\n"
        f"event: {record['event']}\n"
        f"data: {json.dumps(record['data'], ensure_ascii=False)}\n\n"
    )


async def main() -> None:
    store = InMemoryStore()
    thread_id = "thread-store-replay"

    print("=== 写入结构化业务事件 ===")
    await append_progress_event(store, thread_id, "task.accepted", {"status": "PENDING"})
    await append_progress_event(store, thread_id, "task.planning", {"status": "PLANNING"})
    await append_progress_event(store, thread_id, "task.completed", {"status": "COMPLETED"})

    print("\n=== 客户端首次连接：可以拿到完整 progress event ===")
    for record in await replay_progress_events(store, thread_id, last_event_id=None):
        print(format_event(record).strip())

    print("\n=== 客户端断线重连：只回放未消费业务事件 ===")
    for record in await replay_progress_events(store, thread_id, last_event_id=2):
        print(format_event(record).strip())

    print("\n=== token stream 不是 replay 真理源 ===")
    print("  token: 差")
    print("  token: 旅")
    print("  token: 规")
    print("  这些 token 没有写入 store，因此不会在重连时 replay")


if __name__ == "__main__":
    asyncio.run(main())
