"""
解决什么问题: 数据库场景错误码集中管理，保证错误码唯一、与 HTTP 状态码绑定
输入输出约定: ErrorCode 枚举成员带 (code, message, http_status) 三元组，可直接用于构造 AppError
失败策略: 导入时检查错误码唯一性，重复则 RuntimeError
不适用场景: 不适合动态注册错误码的场景；通用业务错误码请在 exception教程 的 ErrorCode 中定义
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """数据库场景错误码注册表。

    每个成员是 (code_str, default_message, http_status) 三元组。
    code 是对外暴露的字符串标识，message 是默认用户可读文案，http_status 是对应 HTTP 状态码。
    """

    # 客户端错误
    VALIDATION_ERROR = ("VALIDATION_ERROR", "参数校验失败", 422)
    NOT_FOUND = ("NOT_FOUND", "资源不存在", 404)
    DUPLICATE = ("DUPLICATE", "资源已存在", 409)
    OPTIMISTIC_LOCK_ERROR = ("OPTIMISTIC_LOCK_ERROR", "数据已被其他操作修改，请刷新后重试", 409)

    # 服务端错误
    DATABASE_ERROR = ("DATABASE_ERROR", "数据库错误", 500)
    CONNECTION_ERROR = ("CONNECTION_ERROR", "数据库连接失败", 502)
    INTERNAL_ERROR = ("INTERNAL_ERROR", "服务器内部错误", 500)

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


# 导入时检查错误码唯一性（用 __members__ 遍历，防止 Enum alias 折叠导致漏检）
_seen_codes: dict[str, str] = {}  # code → member_name
for _name, _member in ErrorCode.__members__.items():
    if _member.code in _seen_codes:
        raise RuntimeError(
            f"Duplicate error code '{_member.code}': "
            f"both {_seen_codes[_member.code]} and {_name}"
        )
    _seen_codes[_member.code] = _name
del _seen_codes, _name, _member


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：打印所有错误码，并用 ErrorCode 构造 AppError。"""
    # 1. 打印所有错误码
    print("=== 数据库场景错误码注册表 ===")
    print(f"  {'枚举名':<25} {'code':<25} {'message':<20} {'http_status'}")
    print(f"  {'-'*25} {'-'*25} {'-'*20} {'-'*11}")
    for ec in ErrorCode:
        print(
            f"  {ec.name:<25} {ec.code:<25} {ec.default_message:<20} {ec.http_status}"
        )
    print()

    # 2. 用 ErrorCode 构造 AppError
    print("=== 用 ErrorCode 构造 AppError ===")
    ec = ErrorCode.NOT_FOUND
    err = AppError(
        error_code=ec,
        detail={"resource": "user", "id": 42},
    )
    print(f"  ErrorCode: {ec}")
    print(f"  AppError:  {err}")
    print(f"  repr:      {err!r}")
    print(f"  code:      {err.code}")
    print(f"  message:   {err.message}")
    print(f"  status:    {err.status_code}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        from .error_base import AppError
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from templates.error_base import AppError  # type: ignore[no-redef]

    _demo()
