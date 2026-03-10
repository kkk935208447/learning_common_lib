"""
目标: 演示 BaseHTTPMiddleware 记录每个请求的耗时
关键 API: APIRouter, BaseHTTPMiddleware, Request, Response
Python 版本: 3.11+
运行命令: uv run python examples/04_middleware_errors/02_custom_middleware.py  (手动探索 /docs)
测试命令: uv run python examples/04_middleware_errors/02_custom_middleware_test.py
生产提醒: BaseHTTPMiddleware 有已知的流式响应限制，高性能场景考虑用纯 ASGI 中间件
"""

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# ---------------------------------------------------------------------------
# 中间件类（需在 app 级别注册）
# ---------------------------------------------------------------------------


class TimingMiddleware(BaseHTTPMiddleware):
    """记录请求处理耗时，添加到响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time"] = f"{duration_ms:.1f}ms"
        print(f"  [{request.method}] {request.url.path} → {response.status_code} ({duration_ms:.1f}ms)")
        return response


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["middleware_errors"])


@router.get("/fast")
async def fast_endpoint():
    return JSONResponse(content={"speed": "fast"})


@router.get("/slow")
async def slow_endpoint():
    await asyncio.sleep(0.1)  # 模拟慢操作
    return JSONResponse(content={"speed": "slow"})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_custom_middleware — 请求耗时")
    app.add_middleware(TimingMiddleware)
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
