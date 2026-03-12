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
    """构造统一格式的 JSONResponse，并合并额外 headers（如 Retry-After）。"""
    from fastapi.responses import JSONResponse

    # 根据 ErrorResponse 生成 JSON 响应体
    resp = JSONResponse(status_code=status_code, content=body.model_dump())
    # 把异常里携带的自定义 headers 合并进来，同时统一加上 X-Request-ID
    merged_headers = dict(headers or {})
    merged_headers["X-Request-ID"] = body.request_id
    for k, v in merged_headers.items():
        resp.headers[k] = v
    return resp


def _resolve_request_id(request, fallback: str) -> str:
    """优先从 request.state 取 request_id，避免 ContextVar reset 后丢失。"""
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


async def _attach_request_id_to_success_response(response, request_id: str):
    """为统一成功 JSON 响应补齐 request_id，保持教程约定的协议一致。

    仅处理普通 JSON dict 响应，避免干扰 204、文件下载、真实流式响应等特殊场景。
    """
    from starlette.responses import Response

    # 关键节点 1：只处理“成功响应”（<400）。错误响应统一由异常处理器构造。
    if response.status_code >= 400:
        return response

    # 关键节点 2：只处理 application/json。非 JSON（HTML、文件、图片、SSE 等）直接放行。
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return response

    # 没有 content-length 的 JSON 响应通常仍处于流式传输状态，不要为补 request_id
    # 把 body_iterator 整包读完，否则会破坏 StreamingResponse 的流式语义。
    # 关键节点 3：只处理“已完整生成 body”的 JSON 响应；没 content-length 通常意味着仍在流式输出。
    if "content-length" not in response.headers:
        return response

    # 关键节点 4：尽量从 response.body 拿到原始 bytes（这是最安全且不会消耗迭代器的方式）。
    # 某些响应对象可能没有 body（例如尚未渲染），才退而求其次读取 body_iterator。
    raw_body = getattr(response, "body", None)
    if raw_body is None:
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return response
        # 注意：这里会“消费”body_iterator，把所有 chunk 读完并拼成完整 body；
        # 因此上面用 content-length 做了一道拦截，避免破坏真实流式响应语义。
        chunks = [chunk async for chunk in body_iterator]
        raw_body = b"".join(chunks)

    # 关键节点 5：空 body 不处理（例如 204/空 JSON 等），直接放行。
    if not raw_body:
        return response

    # 关键节点 6：解析 JSON；解析失败就不碰它（避免把非 JSON 或编码异常的 body 改坏）。
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError):
        payload = None

    # 关键节点 7：只对“标准协议的 dict JSON”补 request_id。
    # - 必须是 dict（数组等结构不补，避免改变业务语义）
    # - 必须具备 code/message/data 三件套（避免误伤其它 JSON）
    # - 只有当原本没有 request_id 时才补齐（尊重上游显式返回的 request_id）
    if isinstance(payload, dict):
        if "request_id" not in payload and {"code", "message", "data"}.issubset(payload):
            payload["request_id"] = request_id
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # 关键节点 8：重建一个新的 Response（更新后的 body + 原 status_code + 原 background）。
    # 这里不用直接修改原 response，是为了兼容不同 Response 子类的内部实现差异。
    new_response = Response(
        content=raw_body,
        status_code=response.status_code,
        background=response.background,
    )
    # 复用原响应头，保留 set-cookie、自定义 header 等副作用，只重算 content-length。
    # 关键节点 9：保留原 raw_headers（尤其是 set-cookie），但剔除旧 content-length 与旧 x-request-id。
    preserved_headers = [
        header
        for header in getattr(response, "raw_headers", ())
        if header[0].lower() not in {b"content-length", b"x-request-id"}
    ]
    # 关键节点 10：只从 new_response 取“新 body 对应的 content-length”，避免长度不一致导致客户端读不到/多读。
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
    在 finally 中用 token reset ContextVar。
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
            response = await call_next(request)  # 在这个 await 期间：1. 业务代码执行 2. 可能抛出 AppError / HTTPException / 其他异常 3. 以及你注册的异常处理器都会运行。 它们都可以用到刚刚设置的 error_context
            # 只对标准 JSON 成功响应补 body.request_id；错误响应已经由异常处理器统一构造。
            response = await _attach_request_id_to_success_response(response, rid)
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
        from .error_base import AppError, NotFoundError, RateLimitedError
        from .error_context import ErrorContext, error_context
        from .fastapi_error_handler import (
            create_request_id_middleware,
            register_exception_handlers,
        )
    # 本地调试时，选择绝对路径导入，避免 ImportError
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
    print("全部执行完毕")
