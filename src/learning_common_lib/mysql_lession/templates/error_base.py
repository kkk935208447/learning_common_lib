"""
解决什么问题: 提供数据库场景的异常基类和异常树，统一异常的结构化字段
输入输出约定: 所有异常绑定 ErrorCode 枚举，code/message/status_code 从 ErrorCode 派生
失败策略: 异常本身就是失败的表达
不适用场景: 不适合替代 Python 内置异常（如 ValueError），只用于业务/应用层异常

字段分组:
  对外（进入 HTTP 响应）: code, message, detail
  对内（仅日志）: internal_message, log_extra, headers

异常层级树:
  AppError
  ├── ClientError (4xx)
  │   ├── NotFoundError (404)
  │   ├── DuplicateError (409)
  │   ├── AppValidationError (422)
  │   └── OptimisticLockError (409)
  └── ServerError (5xx)
      ├── DatabaseError (500)
      └── ConnectionError (502)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

try:
    from .error_registry import ErrorCode
except ImportError:
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
    headers: 附加响应头（如 Retry-After）
    """

    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = ""
    detail: dict | None = None
    internal_message: str | None = None
    log_extra: dict | None = None
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.message:
            self.message = self.error_code.default_message
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
    error_code: ErrorCode = ErrorCode.VALIDATION_ERROR


@dataclass
class ServerError(AppError):
    """服务端错误基类 (5xx)。"""
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR


# --- 客户端错误 ---


@dataclass
class NotFoundError(ClientError):
    """资源不存在 (404)。"""
    error_code: ErrorCode = ErrorCode.NOT_FOUND


@dataclass
class DuplicateError(ClientError):
    """资源已存在 (409)，典型场景：唯一约束冲突。"""
    error_code: ErrorCode = ErrorCode.DUPLICATE


@dataclass
class AppValidationError(ClientError):
    """参数校验失败 (422)。"""
    error_code: ErrorCode = ErrorCode.VALIDATION_ERROR


@dataclass
class OptimisticLockError(ClientError):
    """乐观锁冲突 (409)，数据已被其他操作修改。"""
    error_code: ErrorCode = ErrorCode.OPTIMISTIC_LOCK_ERROR


# --- 服务端错误 ---


@dataclass
class DatabaseError(ServerError):
    """数据库操作失败 (500)。"""
    error_code: ErrorCode = ErrorCode.DATABASE_ERROR


@dataclass
class ConnectionError(ServerError):
    """数据库连接失败 (502)。"""
    error_code: ErrorCode = ErrorCode.CONNECTION_ERROR


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：创建各类异常实例，展示层级捕获和 raise from 链。"""
    # 1. 创建各类异常实例
    errors = [
        AppError(),
        NotFoundError(detail={"resource": "user", "id": 42}),
        DuplicateError(message="用户 alice 已存在"),
        AppValidationError(detail={"field": "email", "reason": "格式不正确"}),
        OptimisticLockError(detail={"resource": "product", "expected_version": 3}),
        DatabaseError(
            internal_message="Deadlock detected",
            log_extra={"sql": "UPDATE products SET stock=10 WHERE id=1"},
        ),
        ConnectionError(),
    ]
    print("=== 异常实例 ===")
    for err in errors:
        print(f"  {err!r}")
        print(f"    str: {err}")
        print(f"    code={err.code}, status={err.status_code}")
        if err.internal_message:
            print(f"    internal_message={err.internal_message}")
        print()

    # 2. 演示 raise ... from ...（Repository 层异常转换的核心模式）
    print("=== raise ... from ... ===")
    try:
        try:
            raise Exception("(pymysql.err.IntegrityError) Duplicate entry 'alice'")
        except Exception as original:
            raise DuplicateError(
                message="用户名已存在",
                detail={"field": "username", "value": "alice"},
                internal_message=str(original),
            ) from original
    except DuplicateError as exc:
        print(f"  caught: {exc}")
        print(f"  __cause__: {exc.__cause__}")
        print()

    # 3. 演示层级捕获
    print("=== 层级捕获 ===")
    try:
        raise NotFoundError(detail={"id": 99})
    except ClientError as exc:
        print(f"  ClientError 层捕获 NotFoundError: {exc}")

    try:
        raise DatabaseError()
    except AppError as exc:
        print(f"  AppError 层捕获 DatabaseError: {exc}")


if __name__ == "__main__":
    _demo()
