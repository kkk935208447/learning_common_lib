"""FastAPI + LangGraph 集成：SSE 流式端点、lifespan 管理、健康检查。"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, MessagesState, StateGraph

try:
    from .checkpoint_manager import CheckpointManager
    from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
    from .store_manager import StoreManager
except ImportError:  # pragma: no cover - 允许直接运行模板文件
    from checkpoint_manager import CheckpointManager
    from runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
    from store_manager import StoreManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局图实例（lifespan 中初始化）
# ---------------------------------------------------------------------------

_graph_instance: Any = None
_runtime_settings: RedisRuntimeSettings | None = None
_checkpoint_manager: CheckpointManager | None = None
_store_manager: StoreManager | None = None
_store_instance: Any = None


def _resolve_thread_id(thread_id: str | None, *, label: str) -> str:
    settings = _runtime_settings or DEFAULT_RUNTIME_SETTINGS
    return thread_id or settings.demo_thread_id(label)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def graph_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan：启动时编译图，关闭时清理资源。"""
    global _graph_instance, _runtime_settings, _checkpoint_manager, _store_manager, _store_instance
    logger.info("正在初始化 LangGraph 图...")
    _runtime_settings = DEFAULT_RUNTIME_SETTINGS
    _checkpoint_manager = CheckpointManager()
    _store_manager = StoreManager()
    checkpointer = await _checkpoint_manager.get_checkpointer()
    _store_instance = await _store_manager.get_store()

    llm = FakeListChatModel(responses=["模板内置的 LangGraph SSE 演示回复。"])

    async def chat_node(state: MessagesState, config: RunnableConfig) -> dict:
        thread_id = config.get("configurable", {}).get("thread_id") or _resolve_thread_id(
            None,
            label="template-chat",
        )
        namespace = _runtime_settings.chat_namespace(thread_id)
        stats_item = await _store_instance.aget(namespace, "stats")
        request_count = 0
        if stats_item is not None:
            request_count = int(stats_item.value.get("request_count", 0))

        await _store_instance.aput(
            namespace,
            "stats",
            {
                "request_count": request_count + 1,
                "last_user_message": state["messages"][-1].content if state["messages"] else "",
            },
        )

        result = llm.invoke(state["messages"])
        return {"messages": [result]}

    builder = StateGraph(MessagesState)
    builder.add_node("chat", chat_node)
    builder.set_entry_point("chat")
    builder.add_edge("chat", END)
    _graph_instance = builder.compile(checkpointer=checkpointer, store=_store_instance)
    yield
    logger.info("正在清理 LangGraph 资源...")
    if _checkpoint_manager is not None:
        await _checkpoint_manager.aclose()
    if _store_manager is not None:
        await _store_manager.aclose()
    _graph_instance = None
    _store_instance = None
    _checkpoint_manager = None
    _store_manager = None
    _runtime_settings = None


# ---------------------------------------------------------------------------
# SSE 流式生成器
# ---------------------------------------------------------------------------

async def _sse_stream(input_data: dict[str, Any], thread_id: str) -> AsyncGenerator[str, None]:
    """SSE 流式输出图执行过程。"""
    config = {"configurable": {"thread_id": thread_id}}
    yield f"data: {json.dumps({'event': 'start', 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
    async for chunk, metadata in _graph_instance.astream(
        input_data,
        config=config,
        stream_mode="messages",
    ):
        content = getattr(chunk, "content", "")
        if not content:
            continue
        yield f"data: {json.dumps({'event': 'token', 'node': metadata.get('langgraph_node'), 'token': content}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)
    yield f"data: {json.dumps({'event': 'end', 'thread_id': thread_id}, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_graph_app(title: str = "LangGraph API") -> FastAPI:
    """创建集成 LangGraph 的 FastAPI 应用。"""
    app = FastAPI(title=title, lifespan=graph_lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """健康检查端点。"""
        status = "ready" if _graph_instance else "not_initialized"
        checkpointer = getattr(_graph_instance, "checkpointer", None)
        return {
            "status": status,
            "store_backend": getattr(_store_instance, "backend", "none"),
            "store_degraded": getattr(_store_instance, "degraded", False),
            "store_last_error": getattr(_store_instance, "last_error", None),
            "checkpoint_backend": getattr(_checkpoint_manager, "backend", "none"),
            "checkpoint_degraded": getattr(_checkpoint_manager, "degraded", False),
            "checkpoint_last_error": getattr(_checkpoint_manager, "last_error", None),
            "checkpointer_type": getattr(checkpointer, "underlying_type_name", type(checkpointer).__name__),
        }

    @app.post("/invoke")
    async def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        """同步调用图。"""
        thread_id = _resolve_thread_id(payload.get("thread_id"), label="invoke")
        input_data = payload.get("input", {})
        config = {"configurable": {"thread_id": thread_id}}
        result = await _graph_instance.ainvoke(input_data, config=config)
        return {"thread_id": thread_id, "result": result["messages"][-1].content}

    @app.post("/stream")
    async def stream(payload: dict[str, Any]) -> StreamingResponse:
        """SSE 流式调用图。"""
        thread_id = _resolve_thread_id(payload.get("thread_id"), label="stream")
        input_data = payload.get("input", {})
        return StreamingResponse(
            _sse_stream(input_data, thread_id),
            media_type="text/event-stream",
        )

    return app


app = create_graph_app()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    """演示 FastAPI 应用创建（不启动服务器）。"""
    print(f"FastAPI 应用已创建: {app.title}")
    print(f"路由列表:")
    for route in app.routes:
        if hasattr(route, "path"):
            print(f"  {getattr(route, 'methods', {'GET'})} {route.path}")
    print("启动命令: uvicorn templates.fastapi_graph_app:app --reload")


if __name__ == "__main__":
    _demo()
