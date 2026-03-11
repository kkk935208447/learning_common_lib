"""
解决什么问题: 错误码枚举注册表，保证错误码唯一、集中管理、支持国际化扩展
输入输出约定: ErrorCode 枚举成员带 code/message/http_status，可直接用于构造 AppError
失败策略: 导入时检查错误码唯一性，重复则 RuntimeError
不适用场景: 不适合动态注册错误码的场景
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """错误码注册表。"""

    # 客户端错误
    VALIDATION_ERROR = ("VALIDATION_ERROR", "参数校验失败", 422)
    NOT_FOUND = ("NOT_FOUND", "资源不存在", 404)
    UNAUTHORIZED = ("UNAUTHORIZED", "未认证", 401)
    FORBIDDEN = ("FORBIDDEN", "无权限", 403)
    DUPLICATE = ("DUPLICATE", "资源已存在", 409)
    RATE_LIMITED = ("RATE_LIMITED", "请求过于频繁", 429)

    # 服务端错误
    INTERNAL_ERROR = ("INTERNAL_ERROR", "服务器内部错误", 500)
    DATABASE_ERROR = ("DATABASE_ERROR", "数据库错误", 500)
    EXTERNAL_SERVICE_ERROR = ("EXTERNAL_SERVICE_ERROR", "外部服务错误", 502)
    SERVICE_UNAVAILABLE = ("SERVICE_UNAVAILABLE", "服务暂不可用", 503)
    GATEWAY_TIMEOUT = ("GATEWAY_TIMEOUT", "网关超时", 504)

    def __init__(self, code: str, message: str, http_status: int) -> None:
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


# 导入时检查错误码唯一性
_seen: set[str] = set()
for _member in ErrorCode:
    if _member.code in _seen:
        raise RuntimeError(f"Duplicate error code: {_member.code}")
    _seen.add(_member.code)
del _seen, _member


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    from .error_base import AppError

    # 1. 打印所有错误码
    print("=== 错误码注册表 ===")
    print(f"  {'枚举名':<25} {'code':<25} {'message':<15} {'http_status'}")
    print(f"  {'-'*25} {'-'*25} {'-'*15} {'-'*11}")
    for ec in ErrorCode:
        print(
            f"  {ec.name:<25} {ec.code:<25} {ec.default_message:<15} {ec.http_status}"
        )
    print()

    # 2. 用 ErrorCode 构造 AppError（ErrorCode 是唯一真源）
    print("=== 用 ErrorCode 构造 AppError ===")
    ec = ErrorCode.NOT_FOUND
    err = AppError(
        error_code=ec,
        detail={"resource": "order", "id": 123},
    )
    print(f"  ErrorCode: {ec}")
    print(f"  AppError:  {err}")
    print(f"  repr:      {err!r}")
    print(f"  code:      {err.code}")
    print(f"  message:   {err.message}")
    print(f"  status:    {err.status_code}")


if __name__ == "__main__":
    import logging
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_base import AppError  # noqa: E402

    # 1. 打印所有错误码
    print("=== 错误码注册表 ===")
    print(f"  {'枚举名':<25} {'code':<25} {'message':<15} {'http_status'}")
    print(f"  {'-'*25} {'-'*25} {'-'*15} {'-'*11}")
    for ec in ErrorCode:
        print(
            f"  {ec.name:<25} {ec.code:<25} {ec.default_message:<15} {ec.http_status}"
        )
    print()

    # 2. 用 ErrorCode 构造 AppError（ErrorCode 是唯一真源）
    print("=== 用 ErrorCode 构造 AppError ===")
    ec = ErrorCode.NOT_FOUND
    err = AppError(
        error_code=ec,
        detail={"resource": "order", "id": 123},
    )
    print(f"  ErrorCode: {ec}")
    print(f"  AppError:  {err}")
    print(f"  repr:      {err!r}")
    print(f"  code:      {err.code}")
    print(f"  message:   {err.message}")
    print(f"  status:    {err.status_code}")
