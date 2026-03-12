"""
解决什么问题: FastAPI 全局异常处理器，一键注册，统一 JSON 响应格式
输入输出约定: register_exception_handlers(app) 注册异常处理器；success_response(...) 构造成功响应；可选 request_id 中间件
失败策略: AppError → 对应 status_code + 统一 JSON；Exception → 500 + 完整日志
不适用场景: 不适合非 FastAPI 框架（但思路可迁移）

统一响应协议:
  成功: {"code": "OK", "message": "success", "data": {...}, "request_id": "..."}  # 路由中显式返回 success_response(...)
  失败: {"code": "NOT_FOUND", "message": "资源不存在", "data": null, "request_id": "..."}
  对内: internal_message + log_extra 仅写入日志
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SuccessResponse(BaseModel):
    """统一成功响应模型，可在路由 response_model= 中声明。"""

    code: str | int = "OK"
    message: str = "success"
    data: Any = None
    request_id: str = "no-request"


class ErrorResponse(BaseModel):
    """统一错误响应模型，可在路由 responses= 中声明。

    与成功响应共享 code + message + data + request_id 结构：
    - 成功时 data 为业务数据
    - 失败时 data 为 null（或包含 errors 字段级细节）
    """

    code: str | int
    message: str
    data: dict | list | None = None
    request_id: str = "no-request"


def _build_response(
    status_code: int,
    body: BaseModel,
    headers: dict | None = None,
):
    """构造统一格式的 JSONResponse，并合并额外 headers（如 Retry-After）。"""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    resp = JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body.model_dump()),
    )
    merged_headers = dict(headers or {})
    request_id = getattr(body, "request_id", None)
    if request_id:
        merged_headers["X-Request-ID"] = request_id
    for k, v in merged_headers.items():
        resp.headers[k] = v
    return resp


def _resolve_request_id(request, fallback: str) -> str:
    """优先从 request.state 取 request_id，避免 ContextVar reset 后丢失。"""
    if request is None:
        return fallback
    # 优先读取中间件注入的 request.state.request_id
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    if request_id:
        return request_id
    # 若没有，则尝试复用上游传入的 X-Request-ID
    inbound_request_id = request.headers.get("x-request-id")
    if inbound_request_id:
        return inbound_request_id
    # 再没有就退回到调用方提供的兜底值（通常来自 ErrorContext）
    return fallback


def success_response(
    data: Any = None,
    *,
    code: str | int = "OK",
    message: str = "success",
    status_code: int = 200,
    headers: dict | None = None,
    request=None,
):
    """构造统一成功 JSON 响应，并显式输出 request_id。

    优先从 request.state 读取 request_id；若路由未接收 request，则退回到
    ContextVar 中的当前上下文。这样成功响应和异常响应都共享同一 request_id。
    """
    from .error_context import get_context

    ctx = get_context()
    request_id = _resolve_request_id(request, ctx.request_id)
    body = SuccessResponse(
        code=code,
        message=message,
        data=data,
        request_id=request_id,
    )
    return _build_response(status_code, body, headers)


def register_exception_handlers(app) -> None:
    """一键注册所有异常处理器。

    用法:
        app = FastAPI()
        register_exception_handlers(app)
    """
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from .error_base import AppError, ClientError
    from .error_context import get_context

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        # 从上下文中获取本次请求的 ErrorContext（含 request_id）
        ctx = get_context()
        request_id = _resolve_request_id(request, ctx.request_id)
        # 4xx → info；5xx → error + exc_info
        if isinstance(exc, ClientError):
            # 对于客户端错误，用 info 级别记录核心信息（不打印堆栈）
            logger.info(
                "%s %s → [%s] %s request_id=%s",
                request.method, request.url.path,
                exc.code, exc.display_message, request_id,
            )
        else:
            # 对于服务端错误，打印完整堆栈 + internal_message + log_extra，方便排查
            logger.error(
                "%s %s → [%s] %s request_id=%s internal=%s extra=%s",
                request.method, request.url.path,
                exc.code, exc.display_message, request_id,
                exc.internal_message, exc.log_extra,
                exc_info=True,
            )
        # 使用统一协议构造错误响应体
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
        ctx = get_context()
        # 使用上下文中的 request_id + 请求头兜底，保证 header/body 一致
        request_id = _resolve_request_id(request, ctx.request_id)
        # detail 可能是 dict 或 str，统一处理
        if isinstance(exc.detail, dict):
            if "code" in exc.detail and "message" in exc.detail:
                # 若 detail 已经是统一协议结构，则直接透传
                code = exc.detail["code"]
                msg = exc.detail["message"]
                data = exc.detail.get("data")
            else:
                # 不是协议结构的 dict，则包装成 HTTP_{status} + message 字段
                code = f"HTTP_{exc.status_code}"
                msg = exc.detail.get("message", str(exc.detail))
                data = exc.detail
        else:
            # 非 dict（字符串等），全部归一到 HTTP_{status} + 文本 message
            code = f"HTTP_{exc.status_code}"
            msg = str(exc.detail) if exc.detail else "请求错误"
            data = None
        # 统一封装为 ErrorResponse，使 HTTPException 也遵守同一 JSON 协议
        body = ErrorResponse(
            code=code,
            message=msg,
            data=data,
            request_id=request_id,
        )
        return _build_response(exc.status_code, body, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError,
    ):
        """RequestValidationError → 稳定摘要 + 可选字段级细节。"""
        ctx = get_context()
        request_id = _resolve_request_id(request, ctx.request_id)
        # 生成可读摘要
        field_errors = []
        for err in exc.errors():
            # loc 形如 ("body", "item", 0, "name")，拼成 body.item.0.name
            loc = ".".join(str(x) for x in err.get("loc", []))
            field_errors.append(f"{loc}: {err.get('msg', '')}")
        summary = "; ".join(field_errors) if field_errors else "请求参数校验失败"
        # data 中保留原始 errors 结构，方便前端精细展示字段级错误
        body = ErrorResponse(
            code="VALIDATION_ERROR",
            message=summary,
            data={"errors": exc.errors()},
            request_id=request_id,
        )
        return _build_response(422, body)

    @app.exception_handler(Exception)
    async def handle_unhandled_error(request: Request, exc: Exception):
        ctx = get_context()
        request_id = _resolve_request_id(request, ctx.request_id)
        # 未捕获异常统一打错误日志 + 完整堆栈，避免静默失败
        logger.error(
            "%s %s → Unhandled error request_id=%s\n%s",
            request.method, request.url.path,
            request_id,
            traceback.format_exc(),
        )
        # 对外隐藏内部细节，只返回固定错误码 + 友好提示
        body = ErrorResponse(
            code="INTERNAL_ERROR",
            message="服务器内部错误",
            request_id=request_id,
        )
        return _build_response(500, body)


def create_request_id_middleware(app) -> None:
    """注册 request_id 中间件。

    优先读取入站 X-Request-ID / X-Trace-ID header，没有才生成完整 UUID。
    中间件只负责设置上下文和响应头；成功响应体由路由显式返回。
    """
    from fastapi import Request

    from .error_context import ErrorContext, error_context, reset_context

    @app.middleware("http")  # 注册一个 FastAPI HTTP 中间件，所有请求都会先经过这个函数。
    async def request_id_middleware(request: Request, call_next):
        #构造本次请求的 request_id： 先看入站头 x-request-id。如果没有，再看 x-trace-id。还没有，就生成一个新的 UUID 字符串
        rid = (
            request.headers.get("x-request-id")
            or request.headers.get("x-trace-id")
            or str(uuid.uuid4())
        )
        ctx = ErrorContext(request_id=rid)
        token = error_context.set(ctx) # 把上面的 ErrorContext 写入一个 ContextVar（error_context），返回的 token 用于之后恢复旧值。
        request.state.request_id = rid
        try:
            # 在这个 await 期间：1. 业务代码执行 2. 可能抛出 AppError / HTTPException / 其他异常
            # 3. 以及你注册的异常处理器都会运行。它们都可以用到刚刚设置的 error_context。
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            # 单次请求结束。 及时恢复 ContextVar，避免同线程复用时把上下文带到下一次请求。
            reset_context(token)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import logging
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    try:
        from .error_base import NotFoundError, RateLimitedError
        from .fastapi_error_handler import (
            create_request_id_middleware,
            register_exception_handlers,
            success_response,
        )
    # 本地调试时，选择绝对路径导入，避免 ImportError
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from templates.error_base import NotFoundError, RateLimitedError
        from templates.fastapi_error_handler import (
            create_request_id_middleware,
            register_exception_handlers,
            success_response,
        )

    app = FastAPI()
    register_exception_handlers(app)
    create_request_id_middleware(app)

    @app.get("/ok")
    async def ok_endpoint():
        return success_response(data={"status": "ok"})

    @app.get("/not-found")
    async def not_found_endpoint():
        raise NotFoundError(detail={"resource": "user", "id": 999})

    @app.get("/rate-limited")
    async def rate_limited_endpoint():
        raise RateLimitedError(
            message="请求过于频繁，请 60 秒后重试",
            headers={"Retry-After": "60"},
        )

    @app.get("/crash")
    async def crash_endpoint():
        raise RuntimeError("unexpected boom")

    @app.get("/http-dict")
    async def http_dict_endpoint():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DUPLICATE",
                "message": "用户名已存在",
                "data": None,
            },
        )

    @app.get("/auth-http")
    async def auth_http_endpoint():
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/validate")
    async def validate_endpoint(count: int = Query(..., gt=0)):
        return success_response(data={"count": count})

    @app.get("/stream-ok")
    async def stream_ok_endpoint():
        def body_iter():
            yield b'{"code":"OK","message":"success","data":{"stream":true}}'

        return StreamingResponse(body_iter(), media_type="application/json")

    client = TestClient(app, raise_server_exceptions=False)

    endpoints = [
        ("GET", "/ok"),
        ("GET", "/stream-ok"),
        ("GET", "/not-found"),
        ("GET", "/rate-limited"),
        ("GET", "/crash"),
        ("GET", "/http-dict"),
        ("GET", "/auth-http"),
        ("GET", "/validate?count=abc"),
        ("GET", "/nonexistent-route"),
    ]

    for method, path in endpoints:
        print(f"\n{'='*50}")
        print(f"{method} {path}")
        resp = client.get(path)
        print(f"  status: {resp.status_code}")
        print(f"  body:   {resp.json()}")
        if "X-Request-ID" in resp.headers:
            print(f"  X-Request-ID: {resp.headers['X-Request-ID']}")
        if "Retry-After" in resp.headers:
            print(f"  Retry-After: {resp.headers['Retry-After']}")

        body = resp.json()
        if path == "/ok":
            assert resp.status_code == 200
            assert body == {
                "code": "OK",
                "message": "success",
                "data": {"status": "ok"},
                "request_id": resp.headers["X-Request-ID"],
            }
        elif path == "/stream-ok":
            assert resp.status_code == 200
            assert body == {
                "code": "OK",
                "message": "success",
                "data": {"stream": True},
            }
            assert resp.headers["X-Request-ID"]
        elif path == "/crash":
            assert resp.status_code == 500
            assert body["request_id"] == resp.headers["X-Request-ID"]
            assert body["request_id"] != "no-request"
        elif path == "/http-dict":
            assert resp.status_code == 409
            assert body == {
                "code": "DUPLICATE",
                "message": "用户名已存在",
                "data": None,
                "request_id": resp.headers["X-Request-ID"],
            }
        elif path == "/auth-http":
            assert resp.status_code == 401
            assert resp.headers["WWW-Authenticate"] == "Bearer"
            assert body == {
                "code": "HTTP_401",
                "message": "Unauthorized",
                "data": None,
                "request_id": resp.headers["X-Request-ID"],
            }
        elif path == "/rate-limited":
            assert resp.headers["Retry-After"] == "60"
            assert body["request_id"] == resp.headers["X-Request-ID"]
        elif resp.status_code >= 400:
            assert body["request_id"] == resp.headers["X-Request-ID"]
    print("全部执行完毕")
