"""FastAPI + LangGraph SSE 流式端点。

目标：
    演示 FastAPI 集成 LangGraph 的 SSE（Server-Sent Events）流式端点，
    使用 graph.astream(..., stream_mode="messages") 输出 token 级内容。

关键 API：
    - StreamingResponse —— FastAPI 流式响应
    - graph.astream(..., stream_mode="messages") —— 异步消息流
    - lifespan —— 应用生命周期管理

运行命令：
    uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000

预期现象：
    1. 文件内直接定义可运行的 FastAPI app
    2. `/chat/stream` 以 SSE 方式逐 token 输出内容
    3. `/chat/invoke` 返回非流式完整结果

生产提醒：
    - 面向聊天 UI 的主路径更适合 `stream_mode="messages"`
    - `astream_events()` 更适合调试和可观测性，不应混写成主流 SSE 模式
    - 并发控制：使用 asyncio.Semaphore 限制同时执行的图数量
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, MessagesState, StateGraph


# ══════════════════════════════════════════════════════════
# 图定义
# ══════════════════════════════════════════════════════════

def build_chat_graph():
    """构建聊天图。"""
    llm = FakeListChatModel(
        responses=[
            "这是一个流式回复的模拟内容，用于演示 FastAPI SSE 和 LangGraph messages 流。",
        ]
    )

    def chat_node(state: MessagesState) -> dict:
        result = llm.invoke(state["messages"])
        return {"messages": [result]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile()


# ══════════════════════════════════════════════════════════
# FastAPI 应用
# ══════════════════════════════════════════════════════════

MAX_CONCURRENT = 10
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
graph_app = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期管理。"""
    global graph_app
    print("[lifespan] 初始化 LangGraph 图实例...")
    graph_app = build_chat_graph()
    yield
    print("[lifespan] 清理资源...")
    graph_app = None


async def event_generator(query: str) -> AsyncGenerator[str, None]:
    """将 LangGraph messages 流转换为 SSE。"""
    async with semaphore:
        try:
            start_payload = json.dumps({"event": "start", "query": query}, ensure_ascii=False)
            yield f"data: {start_payload}\n\n"

            async for chunk, metadata in graph_app.astream(
                {"messages": [("human", query)]},
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
    """创建 FastAPI 应用。"""
    app = FastAPI(title="LangGraph SSE API", lifespan=lifespan)

    @app.post("/chat/stream")
    async def chat_stream(query: str = Query(..., description="用户查询")) -> StreamingResponse:
        return StreamingResponse(
            event_generator(query),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/chat/invoke")
    async def chat_invoke(query: str = Query(..., description="用户查询")) -> dict[str, str]:
        result = await graph_app.ainvoke({"messages": [("human", query)]})
        return {"response": result["messages"][-1].content}

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"status": "ok", "graph_loaded": graph_app is not None}

    return app


app = create_app()


# ══════════════════════════════════════════════════════════
# 本地演示
# ══════════════════════════════════════════════════════════

async def demo_sse_flow() -> None:
    """演示 SSE 事件流的生成过程。"""
    global graph_app
    graph_app = build_chat_graph()

    print("模拟 SSE 事件流:\n")
    async for event_str in event_generator("你好，介绍一下 LangGraph"):
        print(f"  {event_str.strip()}")


if __name__ == "__main__":
    print("=== FastAPI + LangGraph SSE 集成演示 ===\n")
    print("已定义可直接启动的 FastAPI app")
    print("路由: POST /chat/stream, POST /chat/invoke, GET /health")
    print("\n--- SSE 事件流演示 ---\n")
    asyncio.run(demo_sse_flow())
    print("\n生产环境启动命令:")
    print("  uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000")
