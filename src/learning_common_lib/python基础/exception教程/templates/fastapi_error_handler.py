"""
解决什么问题: FastAPI 全局异常处理器，一键注册，统一 JSON 响应格式
输入输出约定: register_exception_handlers(app) 注册所有处理器，可选 request_id 中间件
失败策略: AppError → 对应 status_code + 统一 JSON；Exception → 500 + 完整日志
不适用场景: 不适合非 FastAPI 框架（但思路可迁移）

统一响应协议:
  成功: {"code": "OK", "message": "success", "data": {...}, "request_id": "..."}  # 普通 JSON 接口
  失败: {"code": "NOT_FOUND", "message": "资源不存在", "data": null, "request_id": "..."}
  对内: internal_message + log_extra 仅写入日志
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid

from pydantic import BaseModel

logger = logging.getLogger(__name__)


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


def _build_response(status_code: int, body: ErrorResponse, headers: dict | None = None):
    """构造 JSONResponse，附加可选 headers（如 Retry-After）。"""
    from fastapi.responses import JSONResponse

    resp = JSONResponse(status_code=status_code, content=body.model_dump())
    merged_headers = dict(headers or {})
    merged_headers["X-Request-ID"] = body.request_id
    for k, v in merged_headers.items():
        resp.headers[k] = v
    return resp


def _resolve_request_id(request, fallback: str) -> str:
    """优先从 request.state 取 request_id，避免 ContextVar reset 后丢失。"""
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    if request_id:
        return request_id
    inbound_request_id = request.headers.get("x-request-id")
    if inbound_request_id:
        return inbound_request_id
    return fallback


async def _attach_request_id_to_success_response(response, request_id: str):
    """为统一成功 JSON 响应补齐 request_id，保持教程约定的协议一致。

    仅处理普通 JSON dict 响应，避免干扰 204、文件下载、真实流式响应等特殊场景。
    """
    from starlette.responses import Response

    if response.status_code >= 400:
        return response

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return response

    # 没有 content-length 的 JSON 响应通常仍处于流式传输状态，不要为补 request_id
    # 把 body_iterator 整包读完，否则会破坏 StreamingResponse 的流式语义。
    if "content-length" not in response.headers:
        return response

    raw_body = getattr(response, "body", None)
    if raw_body is None:
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return response
        chunks = [chunk async for chunk in body_iterator]
        raw_body = b"".join(chunks)

    if not raw_body:
        return response

    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        payload = None

    if isinstance(payload, dict):
        if "request_id" not in payload and {"code", "message", "data"}.issubset(payload):
            payload["request_id"] = request_id
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    new_response = Response(
        content=raw_body,
        status_code=response.status_code,
        background=response.background,
    )
    # 复用原响应头，保留 set-cookie、自定义 header 等副作用，只重算 content-length。
    preserved_headers = [
        header
        for header in getattr(response, "raw_headers", ())
        if header[0].lower() not in {b"content-length", b"x-request-id"}
    ]
    generated_headers = [
        header
        for header in getattr(new_response, "raw_headers", ())
        if header[0].lower() == b"content-length"
    ]
    new_response.raw_headers = list(preserved_headers + generated_headers)
    return new_response


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
        ctx = get_context()
        request_id = _resolve_request_id(request, ctx.request_id)
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
        ctx = get_context()
        request_id = _resolve_request_id(request, ctx.request_id)
        # detail 可能是 dict 或 str，统一处理
        if isinstance(exc.detail, dict):
            if "code" in exc.detail and "message" in exc.detail:
                code = exc.detail["code"]
                msg = exc.detail["message"]
                data = exc.detail.get("data")
            else:
                code = f"HTTP_{exc.status_code}"
                msg = exc.detail.get("message", str(exc.detail))
                data = exc.detail
        else:
            code = f"HTTP_{exc.status_code}"
            msg = str(exc.detail) if exc.detail else "请求错误"
            data = None
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
            loc = ".".join(str(x) for x in err.get("loc", []))
            field_errors.append(f"{loc}: {err.get('msg', '')}")
        summary = "; ".join(field_errors) if field_errors else "请求参数校验失败"
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
        logger.error(
            "%s %s → Unhandled error request_id=%s\n%s",
            request.method, request.url.path,
            request_id,
            traceback.format_exc(),
        )
        body = ErrorResponse(
            code="INTERNAL_ERROR",
            message="服务器内部错误",
            request_id=request_id,
        )
        return _build_response(500, body)


def create_request_id_middleware(app) -> None:
    """注册 request_id 中间件。

    优先读取入站 X-Request-ID / X-Trace-ID header，没有才生成完整 UUID。
    在 finally 中用 token reset ContextVar。
    """
    from fastapi import Request

    from .error_context import ErrorContext, error_context, reset_context

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = (
            request.headers.get("x-request-id")
            or request.headers.get("x-trace-id")
            or str(uuid.uuid4())
        )
        ctx = ErrorContext(request_id=rid)
        token = error_context.set(ctx)
        request.state.request_id = rid
        try:
            response = await call_next(request)
            # 只对标准 JSON 成功响应补 body.request_id；错误响应由异常处理器统一构造。
            response = await _attach_request_id_to_success_response(response, rid)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            # 及时恢复 ContextVar，避免同线程复用时把上下文带到下一次请求。
            reset_context(token)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import logging
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    from templates.error_base import AppError, NotFoundError, RateLimitedError
    from templates.error_context import ErrorContext, error_context
    from templates.fastapi_error_handler import (
        create_request_id_middleware,
        register_exception_handlers,
    )

    app = FastAPI()
    register_exception_handlers(app)
    create_request_id_middleware(app)

    @app.get("/ok")
    async def ok_endpoint():
        return {"code": "OK", "message": "success", "data": {"status": "ok"}}

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
        return {"code": "OK", "message": "success", "data": {"count": count}}

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
