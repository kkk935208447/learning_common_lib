"""
目标: 用最小代码讲清 202 / 429 / 502 / 503 / 504 的使用场景
关键 API: APIRouter, BackgroundTasks, HTTPException, RequestValidationError, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/10_status_codes/02_async_and_rate_limit.py
测试命令: uv run python examples/10_status_codes/02_async_and_rate_limit_test.py
生产提醒: 202 适合异步任务；429 必须带 Retry-After；502/503/504 用来表达不同类型的上游故障
"""

import asyncio
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

router = APIRouter(tags=["status_codes"])
_tasks: dict[str, str] = {}
_rate_limit: dict[str, list[float]] = {}

RATE_LIMIT_MAX = 3
RATE_LIMIT_WINDOW = 10.0


def success(message: str, data):
    return {
        "code": 0,
        "message": message,
        "data": data,
    }


def api_error(status_code: int, code: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "data": None,
        },
    )


def register_status_exception_handlers(app) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code * 100,
                "message": str(exc.detail),
                "data": None,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_error = exc.errors()[0]
        field = first_error.get("loc", ["body"])[-1]
        message = first_error.get("msg", "参数校验失败")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": 42200,
                "message": f"参数 '{field}' 校验失败: {message}",
                "data": None,
            },
        )


@router.post("/test/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_state():
    _tasks.clear()
    _rate_limit.clear()


async def process_report(task_id: str) -> None:
    """模拟后台异步任务。"""
    await asyncio.sleep(0.2)
    _tasks[task_id] = "completed"


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
async def create_report(background_tasks: BackgroundTasks):
    """
    202 Accepted:
    请求已经接收，但任务还没有真正执行完成。
    """
    task_id = f"task_{int(time.time() * 1000)}"
    _tasks[task_id] = "processing"
    background_tasks.add_task(process_report, task_id)
    return success(
        message="报表任务已提交",
        data={
            "task_id": task_id,
            "status": "processing",
            "poll_url": f"/reports/{task_id}",
        },
    )


@router.get("/reports/{task_id}")
async def get_report_status(task_id: str):
    status_text = _tasks.get(task_id)
    if not status_text:
        raise api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code=40402,
            message="任务不存在",
        )

    return success(
        message="查询成功",
        data={"task_id": task_id, "status": status_text},
    )


@router.get("/limited")
async def limited_endpoint(request: Request):
    """
    429 Too Many Requests:
    触发限流时，除了状态码，还应该带 Retry-After 响应头。
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    timestamps = _rate_limit.get(client_ip, [])
    timestamps = [item for item in timestamps if now - item < RATE_LIMIT_WINDOW]

    if len(timestamps) >= RATE_LIMIT_MAX:
        retry_after = int(RATE_LIMIT_WINDOW - (now - timestamps[0])) + 1
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "code": 42900,
                "message": "请求过于频繁，请稍后再试",
                "data": None,
            },
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)
    _rate_limit[client_ip] = timestamps
    return success(
        message="请求成功",
        data={"remaining": RATE_LIMIT_MAX - len(timestamps)},
    )


@router.get("/proxy/bad-gateway")
async def proxy_bad_gateway():
    """
    502 Bad Gateway:
    网关拿到了上游的错误响应，通常是协议/格式异常。
    """
    raise api_error(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code=50200,
        message="上游网关返回了非法响应",
    )


@router.get("/proxy/unavailable")
async def proxy_unavailable():
    """
    503 Service Unavailable:
    上游服务当前不可用，比如维护中、过载、熔断中。
    """
    raise api_error(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code=50300,
        message="上游服务暂时不可用",
    )


@router.get("/proxy/timeout")
async def proxy_timeout():
    """
    504 Gateway Timeout:
    上游有可能在线，但它响应太慢，已经超时。
    """
    try:
        await asyncio.wait_for(asyncio.sleep(10), timeout=0.1)
    except asyncio.TimeoutError:
        raise api_error(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code=50400,
            message="上游服务响应超时",
        )


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_async_and_rate_limit")
    register_status_exception_handlers(app)
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
