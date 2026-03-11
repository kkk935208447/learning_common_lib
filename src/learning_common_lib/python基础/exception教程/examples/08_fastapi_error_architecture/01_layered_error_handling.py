"""
目标: 演示完整的 FastAPI 4 层错误架构（使用 TestClient 自测，不需要启动服务器）
关键 API: FastAPI, HTTPException, TestClient, exception_handler
Python 版本: 3.11+
运行命令: uv run python examples/08_fastapi_error_architecture/01_layered_error_handling.py  (从 exception教程/ 目录)
预期现象: 展示统一的错误响应格式，不同层的异常如何被转换和处理
生产提醒: Controller 层不做异常处理是关键设计——让异常自然冒泡到全局处理器，保持路由函数简洁
"""

import uuid
from dataclasses import dataclass
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel


# ============================================================
# 第零层：错误码注册表（唯一真源）
# ============================================================

class ErrorCode(Enum):
    """错误码枚举，code/message/http_status 全部从这里派生。"""
    VALIDATION_ERROR = ("VALIDATION_ERROR", "参数校验失败", 422)
    NOT_FOUND = ("NOT_FOUND", "资源不存在", 404)
    DATABASE_ERROR = ("DATABASE_ERROR", "数据库错误", 500)
    INTERNAL_ERROR = ("INTERNAL_ERROR", "服务器内部错误", 500)

    def __init__(self, code: str, message: str, http_status: int):
        self._code = code
        self._message = message
        self._http_status = http_status

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._message

    @property
    def http_status(self) -> int:
        return self._http_status


# ============================================================
# 第一层：异常定义（绑定 ErrorCode + 公开/内部字段分离）
# ============================================================

@dataclass
class AppError(Exception):
    """应用异常基类，绑定 ErrorCode 枚举。

    对外字段: code, message, detail（进入 HTTP 响应）
    对内字段: internal_message, log_extra（仅日志）
    """
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str | None = None
    detail: dict | None = None
    internal_message: str | None = None

    @property
    def code(self) -> str:
        return self.error_code.code

    @property
    def status_code(self) -> int:
        return self.error_code.http_status

    @property
    def display_message(self) -> str:
        return self.message or self.error_code.default_message

    def __str__(self) -> str:
        return f"[{self.code}] {self.display_message}"


@dataclass
class ClientError(AppError):
    pass


@dataclass
class NotFoundError(ClientError):
    error_code: ErrorCode = ErrorCode.NOT_FOUND


@dataclass
class AppValidationError(ClientError):
    error_code: ErrorCode = ErrorCode.VALIDATION_ERROR


@dataclass
class DatabaseError(AppError):
    error_code: ErrorCode = ErrorCode.DATABASE_ERROR


class ErrorResponse(BaseModel):
    """统一错误响应模型（与成功响应共享 code+message+data+request_id 协议）。"""
    code: str
    message: str
    data: dict | list | None = None
    request_id: str = "unknown"


# ============================================================
# 第二层：Repository 层 — 捕获底层异常，raise from
# ============================================================

FAKE_DB: dict[int, dict] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
}


def user_repository_get(user_id: int) -> dict | None:
    """仓储层：访问数据库，边界转换异常。"""
    if user_id == 999:
        try:
            raise ConnectionRefusedError("PostgreSQL connection refused")
        except ConnectionRefusedError as e:
            raise DatabaseError(
                message="数据库连接失败",
                internal_message="PostgreSQL connection refused on port 5432",
            ) from e
    return FAKE_DB.get(user_id)


# ============================================================
# 第三层：Service 层 — 业务逻辑判断
# ============================================================

def user_service_find(user_id: int) -> dict:
    """服务层：业务逻辑校验，底层异常透传。"""
    if user_id <= 0:
        raise AppValidationError(
            message=f"用户 ID 必须为正整数，收到: {user_id}"
        )
    user = user_repository_get(user_id)
    if user is None:
        raise NotFoundError(message=f"用户 {user_id} 不存在")
    return user


# ============================================================
# 第四层：Controller 层（路由）— 不做异常处理
# ============================================================

app = FastAPI()


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求生成唯一 request_id。"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/users/{user_id}")
async def get_user(user_id: int, request: Request):
    """控制器只调用 service，不做异常处理。"""
    user = user_service_find(user_id)
    return {
        "code": "OK",
        "message": "success",
        "data": user,
        "request_id": request.state.request_id,
    }


@app.get("/crash")
async def crash_endpoint():
    """模拟未知异常的路由。"""
    raise RuntimeError("something went terribly wrong")


# ============================================================
# 异常处理器层 — 统一 JSON 响应（日志分级：4xx info / 5xx error）
# ============================================================

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """处理所有 AppError 子类，返回统一 JSON。"""
    request_id = getattr(request.state, "request_id", "unknown")
    if isinstance(exc, ClientError):
        print(f"  [{request_id}] INFO: {exc}")
    else:
        print(f"  [{request_id}] ERROR: {exc} internal={exc.internal_message}")
    body = ErrorResponse(
        code=exc.code,
        message=exc.display_message,
        data=exc.detail,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """兜底处理器：未知异常转 500。"""
    request_id = getattr(request.state, "request_id", "unknown")
    print(f"  [{request_id}] ERROR (unhandled): {exc!r}")
    body = ErrorResponse(
        code="INTERNAL_ERROR",
        message="服务器内部错误",
        request_id=request_id,
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(),
    )


# ============================================================
# 使用 TestClient 自测
# ============================================================

def print_response(label: str, resp) -> None:
    """格式化打印响应。"""
    print(f"\n--- {label} ---")
    print(f"  Status: {resp.status_code}")
    print(f"  X-Request-ID: {resp.headers.get('x-request-id', 'N/A')}")
    try:
        body = resp.json()
        for key, value in body.items():
            print(f"  {key}: {value}")
    except Exception:
        print(f"  Body: {resp.text}")


if __name__ == "__main__":
    client = TestClient(app, raise_server_exceptions=False)

    print("=" * 60)
    print("FastAPI 4 层错误架构演示（TestClient 自测）")
    print("=" * 60)

    print_response(
        "场景 1: 正常请求 GET /users/1 → 200",
        client.get("/users/1"),
    )
    print_response(
        "场景 2: 参数校验失败 GET /users/-1 → 422 AppValidationError",
        client.get("/users/-1"),
    )
    print_response(
        "场景 3: 资源不存在 GET /users/42 → 404 NotFoundError",
        client.get("/users/42"),
    )
    print_response(
        "场景 4: 数据库错误 GET /users/999 → 500 DatabaseError",
        client.get("/users/999"),
    )
    print_response(
        "场景 5: 未知异常 GET /crash → 500 INTERNAL_ERROR",
        client.get("/crash"),
    )

    print(f"\n{'=' * 60}")
    print("=== 4 层架构总结 ===")
    print("=" * 60)
    print("""
  ErrorCode 注册表: 错误码唯一真源（code/message/status_code 全部派生）
       ↓
  异常定义层:  AppError 绑定 ErrorCode，字段分为对外(message/detail→data)和对内(internal_message)
       ↓
  Repository 层: 捕获底层异常 → raise DatabaseError from e
       ↓
  Service 层:    业务逻辑判断 → raise NotFoundError / AppValidationError
       ↓
  Controller 层: 不做异常处理，只调用 service
       ↓
  异常处理器:   ClientError → info 日志；ServerError → error 日志 + exc_info
               统一 ErrorResponse(code+message+data+request_id) 输出 JSON
""")