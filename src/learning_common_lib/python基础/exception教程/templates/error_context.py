"""
解决什么问题: 在请求生命周期中传递错误上下文（request_id、user_id、操作名称等）
输入输出约定: ErrorContext dataclass + ContextVar，在中间件中设置，在异常处理中读取
失败策略: 如果上下文未设置，返回默认值
不适用场景: 不适合跨进程传递上下文（需要分布式追踪）
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _new_context() -> "ErrorContext":
    """返回一个全新的默认上下文，避免共享可变默认值。"""
    return ErrorContext()


@dataclass
class ErrorContext:
    """错误上下文，在请求生命周期中传递。"""

    request_id: str = "no-request"
    user_id: str | None = None
    operation: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }
        if self.user_id:
            d["user_id"] = self.user_id
        if self.operation:
            d["operation"] = self.operation
        if self.extra:
            d["extra"] = self.extra
        return d


# 全局 ContextVar
# None 表示当前上下文未显式设置；get_context() 会在读取时返回一个全新的默认对象。
error_context: ContextVar[ErrorContext | None] = ContextVar(
    "error_context",
    default=None,
)


def get_context() -> ErrorContext:
    """获取当前错误上下文。"""
    ctx = error_context.get()
    if ctx is None:
        return _new_context()
    return ctx


def set_context(**kwargs) -> tuple[ErrorContext, Token]:
    """设置当前错误上下文，返回 (ctx, token)。

    调用方应在 finally 中用 token 重置：
        ctx, token = set_context(request_id=rid)
        try:
            ...
        finally:
            reset_context(token)
    """
    ctx = ErrorContext(**kwargs)
    token = error_context.set(ctx)
    return ctx, token


def reset_context(token: Token) -> None:
    """用 token 重置 ContextVar，恢复到之前的值。"""
    error_context.reset(token)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    # 1. 模拟中间件设置上下文
    print("=== 模拟中间件设置上下文 ===")
    ctx, token = set_context(
        request_id="abc-1234",
        user_id="user-42",
        operation="create_order",
        extra={"ip": "192.168.1.1"},
    )
    print(f"  设置上下文: {ctx}")
    print(f"  to_dict: {ctx.to_dict()}")
    print()

    # 2. 模拟在深层调用栈中读取上下文
    print("=== 深层调用栈读取上下文 ===")

    def service_layer() -> None:
        def repository_layer() -> None:
            current = get_context()
            logger.info(
                "repository 层读取到 request_id=%s, user_id=%s",
                current.request_id,
                current.user_id,
            )
            print(f"  repository 层: request_id={current.request_id}")

        repository_layer()

    service_layer()
    print()

    # 3. 用 token 重置上下文
    print("=== token reset ===")
    reset_context(token)
    after = get_context()
    print(f"  reset 后 request_id: {after.request_id}")
    print()

    # 4. 默认上下文
    print("=== 默认上下文（未设置时） ===")
    from contextvars import copy_context

    def check_default() -> None:
        default = get_context()
        print(f"  默认 request_id: {default.request_id}")
        print(f"  默认 to_dict: {default.to_dict()}")

    # 默认上下文必须是新对象，避免可变 extra 跨请求泄漏
    default_a = get_context()
    default_a.extra["leak"] = "yes"
    default_b = get_context()
    assert "leak" not in default_b.extra
    print("  默认上下文不会共享可变 extra")

    new_ctx = copy_context()
    new_ctx.run(check_default)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    _demo()
