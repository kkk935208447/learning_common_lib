"""FastAPI + LangGraph SSE 流式端点

目标：
    演示 FastAPI 集成 LangGraph 的 SSE（Server-Sent Events）流式端点，
    实现实时 token 级别的流式输出。

关键 API：
    - StreamingResponse —— FastAPI 流式响应
    - graph.astream_events(version="v2") —— 异步事件流
    - lifespan —— 应用生命周期管理

运行命令：
    # 本文件仅演示代码结构，不直接运行服务器
    # 生产环境: uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000
    python 01_fastapi_sse_integration.py

预期现象：
    打印 FastAPI 应用结构和端点信息，演示 SSE 事件生成器的工作方式。

生产提醒：
    - 使用 lifespan 管理图实例的创建和销毁
    - SSE 连接需要设置合理的超时时间
    - 并发控制：使用 asyncio.Semaphore 限制同时执行的图数量
    - 生产环境建议添加认证中间件和速率限制
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator, TypedDict

from langchain_community.chat_models import FakeListChatModel
from langgraph.graph import END, MessagesState, StateGraph


# ══════════════════════════════════════════════════════════
# 图定义
# ══════════════════════════════════════════════════════════

def build_chat_graph():
    """构建聊天图"""
    # 使用 FakeListChatModel 模拟
    # 生产环境替换为: ChatOpenAI(model="gpt-4o", streaming=True)
    llm = FakeListChatModel(responses=["这是一个流式回复的模拟内容。"])

    def chat_node(state: MessagesState) -> dict:
        result = llm.invoke(state["messages"])
        return {"messages": [result]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile()


# ══════════════════════════════════════════════════════════
# FastAPI 应用（演示结构）
# ══════════════════════════════════════════════════════════

# 并发控制信号量
MAX_CONCURRENT = 10
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# 全局图实例（由 lifespan 管理）
graph_app = None


@asynccontextmanager
async def lifespan(app):
    """应用生命周期管理：启动时创建图，关闭时清理资源"""
    global graph_app
    print("[lifespan] 初始化 LangGraph 图实例...")
    graph_app = build_chat_graph()
    yield
    print("[lifespan] 清理资源...")
    graph_app = None


async def event_generator(query: str) -> AsyncGenerator[str, None]:
    """SSE 事件生成器

    将 LangGraph 的 astream_events 转换为 SSE 格式。
    每个 token 作为一个 SSE 事件发送。
    """
    async with semaphore:  # 并发控制
        try:
            async for event in graph_app.astream_events(
                {"messages": [("human", query)]},
                version="v2",
            ):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        payload = json.dumps(
                            {"token": chunk.content},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"

            # 发送结束标记
            yield "data: [DONE]\n\n"

        except Exception as e:
            error_payload = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"


# ── FastAPI 路由定义（演示代码，需要 fastapi 依赖）──
def create_app():
    """创建 FastAPI 应用

    实际使用时取消注释以下代码：
    ```python
    from fastapi import FastAPI, Query
    from fastapi.responses import StreamingResponse
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="LangGraph SSE API", lifespan=lifespan)

    # CORS 中间件（允许前端跨域访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/chat/stream")
    async def chat_stream(query: str = Query(..., description="用户查询")):
        return StreamingResponse(
            event_generator(query),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
            },
        )

    @app.post("/chat/invoke")
    async def chat_invoke(query: str = Query(...)):
        result = await graph_app.ainvoke({"messages": [("human", query)]})
        return {"response": result["messages"][-1].content}

    @app.get("/health")
    async def health():
        return {"status": "ok", "graph_loaded": graph_app is not None}
    ```
    """
    print("FastAPI 应用结构已定义（需要 fastapi + uvicorn 依赖）")


# ══════════════════════════════════════════════════════════
# 本地演示（不启动服务器）
# ══════════════════════════════════════════════════════════

async def demo_sse_flow() -> None:
    """演示 SSE 事件流的生成过程"""
    global graph_app
    graph_app = build_chat_graph()

    print("模拟 SSE 事件流:\n")
    async for event_str in event_generator("你好，介绍一下 LangGraph"):
        print(f"  {event_str.strip()}")


if __name__ == "__main__":
    print("=== FastAPI + LangGraph SSE 集成演示 ===\n")

    create_app()

    print("\n--- SSE 事件流演示 ---\n")
    asyncio.run(demo_sse_flow())

    print("\n生产环境启动命令:")
    print("  uvicorn 01_fastapi_sse_integration:app --host 0.0.0.0 --port 8000")
