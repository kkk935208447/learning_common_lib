"""FastAPI + LangGraph 集成：SSE 流式端点、lifespan 管理、健康检查。"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局图实例（lifespan 中初始化）
# ---------------------------------------------------------------------------

_graph_instance: Any = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def graph_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan：启动时编译图，关闭时清理资源。"""
    global _graph_instance
    logger.info("正在初始化 LangGraph 图...")
    # 实际项目中在此编译图、初始化 checkpointer
    _graph_instance = {"status": "ready"}
    yield
    logger.info("正在清理 LangGraph 资源...")
    _graph_instance = None


# ---------------------------------------------------------------------------
# SSE 流式生成器
# ---------------------------------------------------------------------------

async def _sse_stream(input_data: dict[str, Any], thread_id: str) -> AsyncGenerator[str, None]:
    """SSE 流式输出图执行过程。"""
    # 实际项目中：graph.astream(input_data, config={"configurable": {"thread_id": thread_id}})
    yield f"data: {json.dumps({'event': 'start', 'thread_id': thread_id}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'event': 'node', 'node': 'agent', 'data': input_data}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'event': 'end', 'thread_id': thread_id}, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_graph_app(title: str = "LangGraph API") -> FastAPI:
    """创建集成 LangGraph 的 FastAPI 应用。"""
    app = FastAPI(title=title, lifespan=graph_lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """健康检查端点。"""
        status = "ready" if _graph_instance else "not_initialized"
        return {"status": status}

    @app.post("/invoke")
    async def invoke(payload: dict[str, Any]) -> dict[str, Any]:
        """同步调用图。"""
        thread_id = payload.get("thread_id", "default")
        input_data = payload.get("input", {})
        # 实际项目中：result = await graph.ainvoke(input_data, config=...)
        return {"thread_id": thread_id, "result": input_data}

    @app.post("/stream")
    async def stream(payload: dict[str, Any]) -> StreamingResponse:
        """SSE 流式调用图。"""
        thread_id = payload.get("thread_id", "default")
        input_data = payload.get("input", {})
        return StreamingResponse(
            _sse_stream(input_data, thread_id),
            media_type="text/event-stream",
        )

    return app


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    """演示 FastAPI 应用创建（不启动服务器）。"""
    app = create_graph_app()
    print(f"FastAPI 应用已创建: {app.title}")
    print(f"路由列表:")
    for route in app.routes:
        if hasattr(route, "path"):
            print(f"  {getattr(route, 'methods', {'GET'})} {route.path}")
    print("启动命令: uvicorn templates.fastapi_graph_app:app --reload")


if __name__ == "__main__":
    _demo()
