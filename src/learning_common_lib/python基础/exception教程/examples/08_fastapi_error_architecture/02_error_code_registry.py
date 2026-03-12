"""
目标: 演示错误码注册表模式 + request_id 中间件
关键 API: Enum, FastAPI, ContextVar, TestClient
Python 版本: 3.11+
运行命令: uv run python examples/08_fastapi_error_architecture/02_error_code_registry.py  (从 exception教程/ 目录)
预期现象: 展示错误码枚举管理、唯一性检查、request_id 贯穿全链路
生产提醒: 错误码注册表是企业级错误管理的基础——保证错误码唯一、集中管理、支持国际化扩展
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel


# ============================================================
# 错误码注册表（唯一真源）
# ============================================================

class ErrorCode(Enum):
    """错误码枚举，每个成员带 code/message/http_status。

    使用枚举保证：
    1. 错误码不重复（枚举值唯一）
    2. 所有错误码集中管理
    3. IDE 自动补全
    """
    # 客户端错误 (4xx)
    VALIDATION_ERROR = ("VALIDATION_ERROR", "参数校验失败", 422)
    NOT_FOUND = ("NOT_FOUND", "资源不存在", 404)
    UNAUTHORIZED = ("UNAUTHORIZED", "未认证", 401)
    FORBIDDEN = ("FORBIDDEN", "无权限", 403)
    DUPLICATE = ("DUPLICATE", "资源已存在", 409)

    # 服务端错误 (5xx)
    INTERNAL_ERROR = ("INTERNAL_ERROR", "服务器内部错误", 500)
    DATABASE_ERROR = ("DATABASE_ERROR", "数据库错误", 500)
    EXTERNAL_SERVICE_ERROR = ("EXTERNAL_SERVICE_ERROR", "外部服务错误", 502)

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


# 导入时校验错误码唯一性
_seen_codes: set[str] = set()
for _member in ErrorCode:
    if _member.code in _seen_codes:
        raise RuntimeError(f"Duplicate error code: {_member.code}")
    _seen_codes.add(_member.code)
del _seen_codes


# ============================================================
# 异常类（绑定 ErrorCode，公开/内部字段分离）
# ============================================================

@dataclass
class AppError(Exception):
    """应用异常，绑定 ErrorCode 枚举。

    对外: code, display_message, detail（进入响应）
    对内: internal_message（仅日志）
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


class ErrorResponse(BaseModel):
    """统一错误响应模型（与成功响应共享 code+message+data+request_id 协议）。"""
    code: str
    message: str
    data: dict | list | None = None
    request_id: str = "no-request"


# ============================================================
# 请求上下文（ContextVar）
# ============================================================
# ContextVar 是 Python 3.7+ 引入的特性，用于在并发/异步环境中维护上下文相关的变量。它的核心作用是：
# 隔离上下文：在不同的执行上下文（如不同的请求/协程）中，ContextVar 可以存储不同的值，互不干扰。
# 避免参数传递：无需通过函数参数层层传递请求 ID，可在任何地方直接访问当前上下文的 request_id。
request_id_var: ContextVar[str] = ContextVar("request_id", default="no-request")


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI()


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """为每个请求生成完整 UUID request_id，存入 ContextVar。"""
    rid = (
        request.headers.get("x-request-id")
        or request.headers.get("x-trace-id")
        or str(uuid.uuid4())
    )
    # 设置当前上下文的 request_id
    request_id_var.set(rid)
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """处理 AppError，返回统一 JSON。"""
    rid = getattr(request.state, "request_id", request_id_var.get())
    body = ErrorResponse(
        code=exc.code,
        message=exc.display_message,
        data=exc.detail,
        request_id=rid,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """兜底处理器：未知异常转 500。"""
    rid = getattr(request.state, "request_id", request_id_var.get())
    print(f"  [{rid}] UNHANDLED: {exc!r}")
    body = ErrorResponse(
        code=ErrorCode.INTERNAL_ERROR.code,
        message=ErrorCode.INTERNAL_ERROR.default_message,
        request_id=rid,
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(),
    )


# ============================================================
# 路由
# ============================================================

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    """获取用户。"""
    if user_id <= 0:
        raise AppError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"用户 ID 必须为正整数，收到: {user_id}",
        )

    users = {1: {"id": 1, "name": "Alice"}}
    user = users.get(user_id)
    if user is None:
        raise AppError(
            error_code=ErrorCode.NOT_FOUND,
            detail={"user_id": user_id},
        )

    return {
        "code": "OK",
        "message": "success",
        "data": user,
        "request_id": request_id_var.get(),
    }


@app.post("/users")
async def create_user(request: Request):
    """创建用户。"""
    body = await request.json()
    name = body.get("name")
    if not name:
        raise AppError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="name 不能为空",
        )
    if name == "existing":
        raise AppError(
            error_code=ErrorCode.DUPLICATE,
            message=f"用户 {name!r} 已存在",
        )
    return {
        "code": "OK",
        "message": "success",
        "data": {"id": 99, "name": name},
        "request_id": request_id_var.get(),
    }


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
    print("错误码注册表 + request_id 中间件演示")
    print("=" * 60)

    print_response(
        "场景 1: 正常请求 GET /users/1 → 200",
        client.get("/users/1"),
    )
    print_response(
        "场景 2: 参数校验 GET /users/-1 → 422 VALIDATION_ERROR",
        client.get("/users/-1"),
    )
    print_response(
        "场景 3: 资源不存在 GET /users/42 → 404 NOT_FOUND",
        client.get("/users/42"),
    )
    print_response(
        "场景 4: 创建用户 POST /users → 200",
        client.post("/users", json={"name": "test"}),
    )
    print_response(
        "场景 5: 重复创建 POST /users → 409 DUPLICATE",
        client.post("/users", json={"name": "existing"}),
    )

    # 错误码注册表一览
    print(f"\n{'=' * 60}")
    print("=== 错误码注册表 ===")
    print("=" * 60)
    print(f"  {'枚举名':<28} {'code':<26} {'HTTP':<6} {'默认消息'}")
    print(f"  {'-' * 28} {'-' * 26} {'-' * 6} {'-' * 20}")
    for member in ErrorCode:
        print(
            f"  {member.name:<28} {member.code:<26} {member.http_status:<6} "
            f"{member.default_message}"
        )

    print(f"\n共 {len(ErrorCode)} 个错误码，全部唯一 ✓")
    print("""
设计要点:
  1. ErrorCode 枚举是唯一真源——code/message/status_code 全部从枚举派生
  2. AppError 绑定 ErrorCode 枚举，不再接受裸字符串
  3. 公开字段(message/detail)进入响应 data，内部字段(internal_message)仅写日志
  4. ErrorResponse 模型约束统一协议：code+message+data+request_id
  5. ContextVar 让 request_id 贯穿全链路（不需要层层传参）
  6. 扩展方向：国际化（根据 Accept-Language 选择消息）
""")