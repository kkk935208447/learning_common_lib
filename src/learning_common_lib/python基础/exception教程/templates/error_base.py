"""
解决什么问题: 提供项目级异常基类和异常树，统一异常的结构化字段
输入输出约定: 所有异常绑定 ErrorCode 枚举，code/message/status_code 从 ErrorCode 派生
失败策略: 异常本身就是失败的表达
不适用场景: 不适合替代 Python 内置异常（如 ValueError），只用于业务/应用层异常

字段分组:
  对外（进入 HTTP 响应）: code, message, detail
  对内（仅日志）: internal_message, log_extra
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

try:
    from .error_registry import ErrorCode
except ImportError:
    # 直接运行时（python templates/error_base.py）使用绝对导入
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_registry import ErrorCode  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


@dataclass
class AppError(Exception):
    """应用异常基类。所有业务异常都应继承此类。

    error_code: ErrorCode 枚举成员（唯一真源）
    message: 用户可读消息，默认从 ErrorCode 取
    detail: 可公开的结构化信息（如 {"field": "email"}）
    internal_message: 内部排障信息（不进入响应）
    log_extra: 日志附加数据（如 SQL、表名，不进入响应）
    headers: 附加响应头（如 Retry-After、WWW-Authenticate）
    """

    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = ""
    detail: dict | None = None
    internal_message: str | None = None
    log_extra: dict | None = None
    headers: dict[str, str] | None = None

    # --- 从 ErrorCode 派生的属性 ---

    def __post_init__(self) -> None:
        # message 对外必须始终可用；未显式传入时回退到 ErrorCode 默认文案。
        if not self.message:
            self.message = self.error_code.default_message
        # 保持标准异常语义，确保 exc.args 可用。
        super().__init__(self.message)

    @property
    def code(self) -> str:
        return self.error_code.code

    @property
    def status_code(self) -> int:
        return self.error_code.http_status

    @property
    def display_message(self) -> str:
        """对外展示的消息。"""
        return self.message
    def __str__(self) -> str:
        parts = [f"[{self.code}] {self.display_message}"]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"message={self.display_message!r}, status_code={self.status_code})"
        )


# --- 中间层 ---


@dataclass
class ClientError(AppError):
    """客户端错误基类 (4xx)。"""

    error_code: ErrorCode = ErrorCode.VALIDATION_ERROR  # 子类覆盖


@dataclass
class ServerError(AppError):
    """服务端错误基类 (5xx)。"""

    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR  # 子类覆盖


# --- 客户端错误 ---


@dataclass
class NotFoundError(ClientError):
    error_code: ErrorCode = ErrorCode.NOT_FOUND


@dataclass
class AppValidationError(ClientError):
    error_code: ErrorCode = ErrorCode.VALIDATION_ERROR


@dataclass
class AuthenticationError(ClientError):
    error_code: ErrorCode = ErrorCode.UNAUTHORIZED


@dataclass
class PermissionDeniedError(ClientError):
    error_code: ErrorCode = ErrorCode.FORBIDDEN


@dataclass
class ConflictError(ClientError):
    error_code: ErrorCode = ErrorCode.DUPLICATE


@dataclass
class RateLimitedError(ClientError):
    error_code: ErrorCode = ErrorCode.RATE_LIMITED


# --- 服务端错误 ---


@dataclass
class DatabaseError(ServerError):
    error_code: ErrorCode = ErrorCode.DATABASE_ERROR


@dataclass
class ExternalServiceError(ServerError):
    error_code: ErrorCode = ErrorCode.EXTERNAL_SERVICE_ERROR


@dataclass
class GatewayTimeoutError(ServerError):
    error_code: ErrorCode = ErrorCode.GATEWAY_TIMEOUT


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    # 1. 创建各类异常实例并打印
    errors = [
        AppError(),
        NotFoundError(detail={"resource": "user", "id": 42}),
        AppValidationError(detail={"field": "email", "reason": "格式不正确"}),
        AuthenticationError(headers={"WWW-Authenticate": "Bearer"}),
        PermissionDeniedError(),
        ConflictError(message="用户 alice 已存在"),
        RateLimitedError(headers={"Retry-After": "60"}),
        DatabaseError(
            detail={"table": "users"},
            internal_message="SELECT * FROM users WHERE id=42 timed out",
            log_extra={"sql": "SELECT * FROM users WHERE id=42"},
        ),
        ExternalServiceError(message="支付网关超时"),
        GatewayTimeoutError(message="上游服务 10s 无响应"),
    ]
    print("=== 异常实例 ===")
    for err in errors:
        assert err.message, "AppError.message must always be populated"
        print(f"  {err!r}")
        print(f"    str: {err}")
        print(f"    code={err.code}, status={err.status_code}")
        if err.internal_message:
            print(f"    internal_message={err.internal_message}")
        if err.headers:
            print(f"    headers={err.headers}")
        print()

    # 2. 演示 raise ... from ...
    print("=== raise ... from ... ===")
    try:
        try:
            raise ConnectionError("connection refused")
        except ConnectionError as original:
            raise DatabaseError(
                detail={"original": str(original)},
                internal_message="PostgreSQL 连接被拒绝",
            ) from original
    except DatabaseError as exc:
        print(f"  caught: {exc}")
        print(f"  __cause__: {exc.__cause__}")
        print()

    # 3. 演示在不同层级捕获
    print("=== 层级捕获 ===")
    try:
        raise NotFoundError(detail={"id": 99})
    except ClientError as exc:
        print(f"  ClientError 层捕获: {exc}")

    try:
        raise DatabaseError()
    except AppError as exc:
        print(f"  AppError 层捕获: {exc}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    _demo()










    # import sys
    # from pathlib import Path

    # sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


    # # 1. 创建各类异常实例并打印
    # errors = [
    #     AppError(),
    #     NotFoundError(detail={"resource": "user", "id": 42}),
    #     AppValidationError(detail={"field": "email", "reason": "格式不正确"}),
    #     AuthenticationError(headers={"WWW-Authenticate": "Bearer"}),
    #     PermissionDeniedError(),
    #     ConflictError(message="用户 alice 已存在"),
    #     RateLimitedError(headers={"Retry-After": "60"}),
    #     DatabaseError(
    #         detail={"table": "users"},
    #         internal_message="SELECT * FROM users WHERE id=42 timed out",
    #         log_extra={"sql": "SELECT * FROM users WHERE id=42"},
    #     ),
    #     ExternalServiceError(message="支付网关超时"),
    #     GatewayTimeoutError(message="上游服务 10s 无响应"),
    # ]
    # print("=== 异常实例 ===")
    # for err in errors:
    #     print(f"  {err!r}")
    #     print(f"    str: {err}")
    #     print(f"    code={err.code}, status={err.status_code}")
    #     if err.internal_message:
    #         print(f"    internal_message={err.internal_message}")
    #     if err.headers:
    #         print(f"    headers={err.headers}")
    #     print()

    # # 2. 演示 raise ... from ...
    # print("=== raise ... from ... ===")
    # try:
    #     try:
    #         raise ConnectionError("connection refused")
    #     except ConnectionError as original:
    #         raise DatabaseError(
    #             detail={"original": str(original)},
    #             internal_message="PostgreSQL 连接被拒绝",
    #         ) from original
    # except DatabaseError as exc:
    #     print(f"  caught: {exc}")
    #     print(f"  __cause__: {exc.__cause__}")
    #     print()

    # # 3. 演示在不同层级捕获
    # print("=== 层级捕获 ===")
    # try:
    #     raise NotFoundError(detail={"id": 99})
    # except ClientError as exc:
    #     print(f"  ClientError 层捕获: {exc}")

    # try:
    #     raise DatabaseError()
    # except AppError as exc:
    #     print(f"  AppError 层捕获: {exc}")
