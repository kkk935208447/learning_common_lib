"""
目标: 演示 SSE (Server-Sent Events) 流式响应，模拟 LLM 逐字输出
关键 API: APIRouter, StreamingResponse, text/event-stream
Python 版本: 3.11+
运行命令: uv run python examples/06_background_streaming/02_sse_streaming.py  (手动探索 /docs)
测试命令: uv run python examples/06_background_streaming/02_sse_streaming_test.py
生产提醒: SSE 是单向的（服务端→客户端），双向通信需要 WebSocket
"""

import asyncio

from fastapi import APIRouter
from starlette.responses import StreamingResponse

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["background_streaming"])


async def llm_stream(prompt: str):
    """模拟 LLM 流式生成：逐词输出。"""
    words = f"你好！关于「{prompt}」，这是一个很好的问题。让我来详细解答。".split("，")
    for chunk in words:
        yield f"data: {chunk}\n\n"
        await asyncio.sleep(0.05)
    yield "data: [DONE]\n\n"


@router.get("/chat/stream")
async def chat_stream(prompt: str = "FastAPI"):
    return StreamingResponse(
        llm_stream(prompt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def countdown_gen(n: int):
    for i in range(n, 0, -1):
        yield f"data: {i}\n\n"
        await asyncio.sleep(0.05)
    yield "data: Go!\n\n"


@router.get("/countdown")
async def countdown(n: int = 5):
    """倒计时流式响应。"""
    return StreamingResponse(countdown_gen(n), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_sse_streaming — SSE 流式响应")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
