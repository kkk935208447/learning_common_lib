"""FastAPI + LangGraph SSE 流式端点（store-backed replay 版）。

目标：
    演示 FastAPI 集成 LangGraph 的 SSE 端点，并补上更真实的生产语义：
    - heartbeat
    - Last-Event-ID 回放
    - 结构化事件与 token 事件分离
    - 结构化事件写入 store 作为 replay 真理源

生产提醒：
    - token 流只适合实时渲染，不适合 durable replay
    - replay 应依赖结构化业务事件真理源，而不是内存 chunk
    - 本例用 RedisStore/InMemoryStore 演示事件持久化接口；生产中应结合真正的事件表或 durable store
    - 本例仍故意省略 client disconnect 检测、事件 ID 并发原子性和 retention/trim
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Header, Query
from fastapi.responses import StreamingResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, MessagesState, StateGraph

try:
    from ...templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        StoreManager,
    )
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import (
        CheckpointManager,
        DEFAULT_RUNTIME_SETTINGS,
        StoreManager,
    )

STRICT_REDIS = DEFAULT_RUNTIME_SETTINGS.strict_redis


def emit_runtime_status() -> None:
    checkpoint_backend = getattr(checkpoint_mgr, "backend", "none")
    checkpoint_degraded = getattr(checkpoint_mgr, "degraded", False)
    store_backend = getattr(store_instance, "backend", "none")
    store_degraded = getattr(store_instance, "degraded", False)
    last_error = getattr(store_instance, "last_error", None) or getattr(checkpoint_mgr, "last_error", None)
    line = (
        "RUNTIME_STATUS "
        f"checkpoint={checkpoint_backend} store={store_backend} "
        f"degraded={checkpoint_degraded or store_degraded} strict={STRICT_REDIS}"
    )
    if last_error:
        line += f" last_error={last_error}"
    print(line)


def require_real_redis_runtime() -> None:
    emit_runtime_status()
    checkpoint_backend = getattr(checkpoint_mgr, "backend", "none")
    checkpoint_degraded = getattr(checkpoint_mgr, "degraded", False)
    store_backend = getattr(store_instance, "backend", "none")
    store_degraded = getattr(store_instance, "degraded", False)
    last_error = getattr(store_instance, "last_error", None) or getattr(checkpoint_mgr, "last_error", None)
    if STRICT_REDIS and (
        checkpoint_backend != "redis"
        or store_backend != "redis"
        or checkpoint_degraded
        or store_degraded
    ):
        raise RuntimeError(
            "FastAPI SSE 集成示例要求真实 Redis backend；"
            f"checkpoint={checkpoint_backend}, store={store_backend}, "
            f"checkpoint_degraded={checkpoint_degraded}, store_degraded={store_degraded}, "
            f"last_error={last_error}"
        )


def resolve_thread_id(thread_id: str | None, *, label: str) -> str:
    return thread_id or DEFAULT_RUNTIME_SETTINGS.demo_thread_id(label)


def event_namespace(thread_id: str) -> tuple[str, str, str]:
    return ("threads", thread_id, "events")


async def store_get(namespace: tuple[str, ...], key: str):
    if hasattr(store_instance, "aget"):
        return await store_instance.aget(namespace, key)
    return store_instance.get(namespace, key)


async def store_put(namespace: tuple[str, ...], key: str, value: dict) -> None:
    if hasattr(store_instance, "aput"):
        await store_instance.aput(namespace, key, value)
        return
    store_instance.put(namespace, key, value)


async def store_search(namespace: tuple[str, ...]):
    if hasattr(store_instance, "asearch"):
        return await store_instance.asearch(namespace, limit=100)
    return store_instance.search(namespace, limit=100)


async def next_event_id(thread_id: str) -> int:
    namespace = event_namespace(thread_id)
    meta = await store_get(namespace, "__meta__")
    current = 1
    if meta is not None:
        current = int(meta.value.get("last_event_id", 0)) + 1
    await store_put(namespace, "__meta__", {"last_event_id": current})
    return current


async def append_event(thread_id: str, event: str, data: dict) -> dict:
    record = {
        "id": await next_event_id(thread_id),
        "event": event,
        "data": {"thread_id": thread_id, **data},
    }
    await store_put(event_namespace(thread_id), f"{record['id']:08d}", record)
    return record


def format_sse_event(record: dict) -> str:
    lines = []
    if record.get("id") is not None:
        lines.append(f"id: {record['id']}")
    lines.append(f"event: {record['event']}")
    lines.append(f"data: {json.dumps(record['data'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


async def replay_events(thread_id: str, last_event_id: int | None) -> list[dict]:
    if last_event_id is None:
        return []
    items = await store_search(event_namespace(thread_id))
    records = [item.value for item in items if item.key != "__meta__"]
    records.sort(key=lambda item: item["id"])
    replay = [item for item in records if item["id"] > last_event_id]
    print(
        f"[replay] thread_id={thread_id} last_event_id={last_event_id} "
        f"replayed_ids={[item['id'] for item in replay]}"
    )
    return replay


def build_chat_graph(store, checkpointer):
    llm = FakeListChatModel(
        responses=[
            "这是一个流式回复的模拟内容，用于演示 heartbeat、回放和 Last-Event-ID。",
        ]
    )

    def chat_node(state: MessagesState) -> dict:
        query = state["messages"][-1].content if state["messages"] else ""
        namespace = DEFAULT_RUNTIME_SETTINGS.chat_namespace("sse-demo")
        stats_item = store.get(namespace, "stats")
        request_count = 0
        if stats_item is not None:
            request_count = int(stats_item.value.get("request_count", 0))
        store.put(
            namespace,
            "stats",
            {
                "request_count": request_count + 1,
                "last_user_message": query,
            },
        )
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=checkpointer, store=store)


MAX_CONCURRENT = 10
HEARTBEAT_INTERVAL_S = 0.02
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
graph_app = None
checkpoint_mgr = None
store_mgr = None
store_instance = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global graph_app, checkpoint_mgr, store_mgr, store_instance
    checkpoint_mgr = CheckpointManager()
    store_mgr = StoreManager()
    checkpointer = await checkpoint_mgr.get_checkpointer()
    store_instance = await store_mgr.get_store()
    graph_app = build_chat_graph(store_instance, checkpointer)
    require_real_redis_runtime()
    yield
    await checkpoint_mgr.aclose()
    await store_mgr.aclose()
    graph_app = None
    checkpoint_mgr = None
    store_mgr = None
    store_instance = None


async def event_generator(
    query: str,
    *,
    thread_id: str | None = None,
    last_event_id: int | None = None,
) -> AsyncGenerator[str, None]:
    async with semaphore:
        effective_thread_id = resolve_thread_id(thread_id, label="stream")

        for record in await replay_events(effective_thread_id, last_event_id):
            yield format_sse_event(record)

        accepted = await append_event(
            effective_thread_id,
            "task.accepted",
            {"query": query, "status": "PENDING"},
        )
        yield format_sse_event(accepted)

        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        print(f"[heartbeat] thread_id={effective_thread_id}")
        yield format_sse_event(
            {
                "event": "heartbeat",
                "data": {"thread_id": effective_thread_id, "ts": "2026-03-26T12:00:00Z"},
            }
        )

        async for chunk, metadata in graph_app.astream(
            {"messages": [("human", query)]},
            config={"configurable": {"thread_id": effective_thread_id}},
            stream_mode="messages",
        ):
            content = getattr(chunk, "content", "")
            if not content:
                continue
            yield format_sse_event(
                {
                    "event": "token",
                    "data": {
                        "thread_id": effective_thread_id,
                        "node": metadata.get("langgraph_node"),
                        "token": content,
                    },
                }
            )

        completed = await append_event(
            effective_thread_id,
            "task.completed",
            {"status": "COMPLETED", "message": "token stream finished"},
        )
        yield format_sse_event(completed)


def create_app() -> FastAPI:
    app = FastAPI(title="LangGraph SSE API", lifespan=lifespan)

    @app.post("/chat/stream")
    async def chat_stream(
        query: str = Query(..., description="用户查询"),
        thread_id: str | None = Query(default=None, description="会话线程 ID；为空时自动生成"),
        last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        return StreamingResponse(
            event_generator(query, thread_id=thread_id, last_event_id=last_event_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/chat/invoke")
    async def chat_invoke(
        query: str = Query(..., description="用户查询"),
        thread_id: str | None = Query(default=None, description="会话线程 ID；为空时自动生成"),
    ) -> dict[str, str]:
        effective_thread_id = resolve_thread_id(thread_id, label="invoke")
        result = await graph_app.ainvoke(
            {"messages": [("human", query)]},
            config={"configurable": {"thread_id": effective_thread_id}},
        )
        return {"thread_id": effective_thread_id, "response": result["messages"][-1].content}

    @app.get("/health")
    async def health() -> dict[str, str | bool | None]:
        return {
            "status": "ok",
            "graph_loaded": graph_app is not None,
            "store_backend": getattr(store_instance, "backend", "none"),
            "store_degraded": getattr(store_instance, "degraded", False),
            "checkpoint_backend": getattr(checkpoint_mgr, "backend", "none"),
            "checkpoint_degraded": getattr(checkpoint_mgr, "degraded", False),
            "last_error": getattr(store_instance, "last_error", None) or getattr(checkpoint_mgr, "last_error", None),
        }

    return app


app = create_app()


async def demo_sse_flow() -> None:
    global graph_app, checkpoint_mgr, store_mgr, store_instance
    checkpoint_mgr = CheckpointManager()
    store_mgr = StoreManager()
    checkpointer = await checkpoint_mgr.get_checkpointer()
    store_instance = await store_mgr.get_store()
    graph_app = build_chat_graph(store_instance, checkpointer)
    thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("sse-demo")

    require_real_redis_runtime()

    print(f"thread_id: {thread_id}")
    print("\n=== 首次连接 ===")
    async for event_str in event_generator("你好，介绍一下 LangGraph", thread_id=thread_id):
        print(event_str.strip())

    print("\n=== 带 Last-Event-ID 的重连 ===")
    async for event_str in event_generator(
        "继续讲讲 checkpoint",
        thread_id=thread_id,
        last_event_id=1,
    ):
        print(event_str.strip())

    await checkpoint_mgr.aclose()
    await store_mgr.aclose()


if __name__ == "__main__":
    print("=== FastAPI + LangGraph SSE 集成演示 ===\n")
    print("路由: POST /chat/stream, POST /chat/invoke, GET /health")
    print("支持: heartbeat / Last-Event-ID / store-backed progress events / token channel\n")
    asyncio.run(demo_sse_flow())
    print("\n生产环境启动命令:")
    print("  uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000")
