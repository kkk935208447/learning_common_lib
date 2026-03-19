"""FastAPI + LangGraph SSE 流式端点。

目标：
    演示 FastAPI 集成 LangGraph 的 SSE（Server-Sent Events）流式端点，
    并以 Redis-first checkpoint/store 作为生产级默认运行时。

关键 API：
    - StreamingResponse —— FastAPI 流式响应
    - graph.astream(..., stream_mode="messages") —— 异步消息流
    - lifespan —— 应用生命周期管理
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableConfig
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


def build_chat_graph(store, checkpointer):
    llm = FakeListChatModel(
        responses=[
            "这是一个流式回复的模拟内容，用于演示 FastAPI SSE 和 Redis-first 运行时。",
        ]
    )

    async def chat_node(state: MessagesState, config: RunnableConfig) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id", DEFAULT_RUNTIME_SETTINGS.demo_thread_id("fallback"))
        namespace = DEFAULT_RUNTIME_SETTINGS.chat_namespace(thread_id)
        stats_item = await store.aget(namespace, "stats")
        request_count = 0
        if stats_item is not None:
            request_count = int(stats_item.value.get("request_count", 0))

        await store.aput(
            namespace,
            "stats",
            {
                "request_count": request_count + 1,
                "last_user_message": state["messages"][-1].content if state["messages"] else "",
            },
        )

        result = llm.invoke(state["messages"])
        return {"messages": [result]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=checkpointer, store=store)


MAX_CONCURRENT = 10
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
graph_app = None
checkpoint_mgr = None
store_mgr = None
store_instance = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global graph_app, checkpoint_mgr, store_mgr, store_instance
    print("[lifespan] 初始化 LangGraph 图实例...")
    checkpoint_mgr = CheckpointManager()
    store_mgr = StoreManager()
    checkpointer = await checkpoint_mgr.get_checkpointer()
    store_instance = await store_mgr.get_store()
    graph_app = build_chat_graph(store_instance, checkpointer)
    require_real_redis_runtime()
    yield
    print("[lifespan] 清理资源...")
    await checkpoint_mgr.aclose()
    await store_mgr.aclose()
    graph_app = None
    checkpoint_mgr = None
    store_mgr = None
    store_instance = None


async def event_generator(query: str, *, thread_id: str | None = None) -> AsyncGenerator[str, None]:
    async with semaphore:
        try:
            effective_thread_id = resolve_thread_id(thread_id, label="stream")
            config = {
                "configurable": {
                    "thread_id": effective_thread_id,
                }
            }
            start_payload = json.dumps(
                {"event": "start", "query": query, "thread_id": effective_thread_id},
                ensure_ascii=False,
            )
            yield f"data: {start_payload}\n\n"

            async for chunk, metadata in graph_app.astream(
                {"messages": [("human", query)]},
                config=config,
                stream_mode="messages",
            ):
                content = getattr(chunk, "content", "")
                if not content:
                    continue
                payload = json.dumps(
                    {
                        "event": "token",
                        "node": metadata.get("langgraph_node"),
                        "token": content,
                    },
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as exc:
            error_payload = json.dumps({"event": "error", "error": str(exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="LangGraph SSE API", lifespan=lifespan)

    @app.post("/chat/stream")
    async def chat_stream(
        query: str = Query(..., description="用户查询"),
        thread_id: str | None = Query(default=None, description="会话线程 ID；为空时自动生成"),
    ) -> StreamingResponse:
        return StreamingResponse(
            event_generator(query, thread_id=thread_id),
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
        config = {
            "configurable": {
                "thread_id": effective_thread_id,
            }
        }
        result = await graph_app.ainvoke({"messages": [("human", query)]}, config=config)
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
    demo_thread_id = DEFAULT_RUNTIME_SETTINGS.demo_thread_id("sse-demo")

    require_real_redis_runtime()

    print(
        f"runtime: store={store_instance.backend}, degraded={store_instance.degraded}, "
        f"checkpoint_backend={checkpoint_mgr.backend}, checkpoint_degraded={checkpoint_mgr.degraded}"
    )
    print(f"thread_id: {demo_thread_id}")
    print("模拟 SSE 事件流:\n")
    async for event_str in event_generator("你好，介绍一下 LangGraph", thread_id=demo_thread_id):
        print(f"  {event_str.strip()}")

    await checkpoint_mgr.aclose()
    await store_mgr.aclose()


if __name__ == "__main__":
    print("=== FastAPI + LangGraph SSE 集成演示 ===\n")
    print("已定义可直接启动的 FastAPI app")
    print("路由: POST /chat/stream, POST /chat/invoke, GET /health")
    print("\n--- SSE 事件流演示 ---\n")
    asyncio.run(demo_sse_flow())
    print("\n生产环境启动命令:")
    print("  uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000")
