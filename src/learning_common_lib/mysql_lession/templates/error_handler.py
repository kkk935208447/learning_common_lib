"""
解决什么问题: FastAPI 全局异常处理器 + request_id 中间件，统一 JSON 响应格式
输入输出约定: register_exception_handlers(app) 一键注册所有处理器；RequestIdMiddleware 自动注入 request_id
失败策略: AppError → 对应 status_code + 统一 JSON；未知 Exception → 500 + 完整日志（不泄漏内部信息）
不适用场景: 不适合非 FastAPI 框架（但思路可迁移）

统一响应协议:
  成功: {"code": "OK", "message": "success", "data": {...}, "request_id": "..."}
  失败: {"code": "NOT_FOUND", "message": "资源不存在", "data": null, "request_id": "..."}
  对内: internal_message + log_extra 仅写入日志
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel

try:
    from .error_registry import ErrorCode
    from .error_base import AppError, ClientError, ServerError
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_registry import ErrorCode  # type: ignore[no-redef]
    from templates.error_base import AppError, ClientError, ServerError  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    """统一错误响应模型。

    与成功响应共享 code + message + data + request_id 结构：
    - 成功时 data 为业务数据
    - 失败时 data 为 null（或包含 errors 字段级细节）
    """

    code: str | int
    message: str
    data: dict | list | None = None
    request_id: str = "no-request"


def _build_response(status_code: int, body: ErrorResponse, headers: dict | None = None):
    """构造统一格式的 JSONResponse，并合并额外 headers。"""
    from fastapi.responses import JSONResponse

    resp = JSONResponse(status_code=status_code, content=body.model_dump())
    merged_headers = dict(headers or {})
    merged_headers["X-Request-ID"] = body.request_id
    for k, v in merged_headers.items():
        resp.headers[k] = v
    return resp


def _resolve_request_id(request) -> str:
    """从 request.state 或 header 中获取 request_id，兜底生成 UUID。"""
    # 优先读取中间件注入的 request.state.request_id
    rid = getattr(getattr(request, "state", None), "request_id", None)
    if rid:
        return rid
    # 尝试复用上游传入的 X-Request-ID
    inbound = request.headers.get("x-request-id")
    if inbound:
        return inbound
    return str(uuid.uuid4())


def register_exception_handlers(app) -> None:
    """一键注册所有异常处理器。

    用法:
        app = FastAPI()
        register_exception_handlers(app)
    """
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        request_id = _resolve_request_id(request)
        # 4xx → info；5xx → error + exc_info
        if isinstance(exc, ClientError):
            logger.info(
                "%s %s → [%s] %s request_id=%s",
                request.method, request.url.path,
                exc.code, exc.display_message, request_id,
            )
        else:
            logger.error(
                "%s %s → [%s] %s request_id=%s internal=%s extra=%s",
                request.method, request.url.path,
                exc.code, exc.display_message, request_id,
                exc.internal_message, exc.log_extra,
                exc_info=True,
            )
        body = ErrorResponse(
            code=exc.code,
            message=exc.display_message,
            data=exc.detail,
            request_id=request_id,
        )
        return _build_response(exc.status_code, body, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def handle_starlette_http(request: Request, exc: StarletteHTTPException):
        """接管 Starlette 内建 HTTP 异常（404/405 等）及手工 raise HTTPException。"""
        request_id = _resolve_request_id(request)
        if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
            code = exc.detail["code"]
            msg = exc.detail["message"]
            data = exc.detail.get("data")
        else:
            code = f"HTTP_{exc.status_code}"
            msg = str(exc.detail) if exc.detail else "请求错误"
            data = None
        body = ErrorResponse(code=code, message=msg, data=data, request_id=request_id)
        return _build_response(exc.status_code, body, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        """RequestValidationError → 可读摘要 + 字段级细节。"""
        request_id = _resolve_request_id(request)
        field_errors = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            field_errors.append(f"{loc}: {err.get('msg', '')}")
        summary = "; ".join(field_errors) if field_errors else "参数校验失败"
        body = ErrorResponse(
            code=ErrorCode.VALIDATION_ERROR.code,
            message=summary,
            data={"errors": exc.errors()},
            request_id=request_id,
        )
        return _build_response(422, body)

    @app.exception_handler(Exception)
    async def handle_generic_exception(request: Request, exc: Exception):
        """兜底处理器：未知异常 → 500 + 完整日志（不泄漏内部信息给客户端）。"""
        request_id = _resolve_request_id(request)
        logger.error(
            "Unhandled exception %s %s request_id=%s",
            request.method, request.url.path, request_id,
            exc_info=True,
        )
        body = ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR.code,
            message=ErrorCode.INTERNAL_ERROR.default_message,
            request_id=request_id,
        )
        return _build_response(500, body)


class RequestIdMiddleware:
    """ASGI 中间件：为每个请求注入 request_id。

    优先从 X-Request-ID header 读取（支持链路追踪），否则自动生成 UUID。
    request_id 存入 request.state 并写入响应头 X-Request-ID。
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope)
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def _demo() -> None:
    """演示：创建 FastAPI 应用，注册异常处理器和 request_id 中间件，用 httpx 测试。"""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    try:
        from .error_base import NotFoundError, DuplicateError, DatabaseError
    except ImportError:
        from templates.error_base import NotFoundError, DuplicateError, DatabaseError  # type: ignore[no-redef]

    @app.get("/ok")
    async def ok_endpoint():
        return {"code": "OK", "message": "success", "data": {"status": "ok"}}

    @app.get("/not-found")
    async def not_found_endpoint():
        raise NotFoundError(detail={"resource": "user", "id": 42})

    @app.get("/duplicate")
    async def duplicate_endpoint():
        raise DuplicateError(message="用户名已存在")

    @app.get("/crash")
    async def crash_endpoint():
        raise RuntimeError("unexpected error")

    @app.get("/db-error")
    async def db_error_endpoint():
        raise DatabaseError(
            internal_message="Deadlock detected",
            log_extra={"sql": "UPDATE products SET stock=10"},
        )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("=== 异常处理器 + request_id 中间件测试 ===\n")

        for path in ["/ok", "/not-found", "/duplicate", "/crash", "/db-error"]:
            resp = await client.get(path)
            rid = resp.headers.get("x-request-id", "N/A")
            print(f"  {path:<15} [{resp.status_code}] request_id={rid}")
            print(f"    body: {resp.json()}")
            print()

        # 测试自定义 X-Request-ID 透传
        resp = await client.get("/ok", headers={"X-Request-ID": "custom-trace-123"})
        rid = resp.headers.get("x-request-id")
        print(f"  自定义 request_id 透传: {rid}")
        assert rid == "custom-trace-123", f"Expected custom-trace-123, got {rid}"
        print("  ✅ 全部测试通过!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_demo())
