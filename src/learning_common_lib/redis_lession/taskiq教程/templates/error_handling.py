"""
解决什么问题: 提供 TaskIQ 任务场景的异常层级树，区分可重试/不可重试异常，统一重试决策
输入输出约定: 所有任务异常继承 TaskError；is_retryable(exc) 返回 bool 判断是否应重试
失败策略: TaskRetryableError 子类 → 自动重试；TaskFatalError 子类 → 立即失败，不重试
不适用场景: 不替代 Python 内置异常；HTTP 层异常请用 FastAPI 异常体系

异常层级树:
  TaskError (基类)
  ├── TaskRetryableError (可重试)
  │   ├── TaskTimeoutError        — 任务超时
  │   ├── TaskRateLimitError      — 触发限流
  │   └── ExternalServiceError    — 外部服务调用失败
  └── TaskFatalError (不可重试)
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------


class TaskError(Exception):
    """TaskIQ 任务异常基类。所有任务相关异常都应继承此类。"""

    def __init__(self, message: str = "", detail: dict[str, Any] | None = None) -> None:
        self.message = message or self.__class__.__doc__ or "任务异常"
        self.detail = detail
        super().__init__(self.message)

    def __repr__(self) -> str:
        parts = [f"{type(self).__name__}({self.message!r})"]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# 中间层
# ---------------------------------------------------------------------------


class TaskRetryableError(TaskError):
    """可重试的任务异常。捕获后应配合 TaskIQ 重试中间件进行重试。"""
    pass


class TaskFatalError(TaskError):
    """不可重试的任务异常。捕获后应立即标记失败，不再重试。"""
    pass


# ---------------------------------------------------------------------------
# 可重试异常
# ---------------------------------------------------------------------------


class TaskTimeoutError(TaskRetryableError):
    """任务执行超时。"""
    pass


class TaskRateLimitError(TaskRetryableError):
    """触发限流，需要等待后重试。"""
    pass


class ExternalServiceError(TaskRetryableError):
    """外部服务调用失败（HTTP 超时、连接拒绝等）。"""
    pass


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试。

    规则:
      1. TaskRetryableError 子类 → True
      2. TaskFatalError 子类 → False
      3. TaskError 但不属于上述两类 → False（保守策略）
      4. 非 TaskError → False（未知异常不自动重试）
    """
    if isinstance(exc, TaskRetryableError):
        return True
    return False


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：异常层级树和 is_retryable 判断。"""
    # 1. 创建各类异常实例
    errors: list[tuple[str, Exception]] = [
        ("TaskError（基类）", TaskError("通用任务错误")),
        ("TaskRetryableError", TaskRetryableError("可重试")),
        ("TaskFatalError", TaskFatalError("不可重试")),
        ("TaskTimeoutError", TaskTimeoutError("执行超时 300s")),
        ("TaskRateLimitError", TaskRateLimitError("超过 100/m 限制")),
        ("ExternalServiceError", ExternalServiceError(
            "支付网关超时", detail={"url": "https://pay.example.com", "timeout": 30}
        )),
    ]

    print("🌳 === 异常层级树 ===")
    for label, err in errors:
        retryable = is_retryable(err)
        icon = "🔄" if retryable else "❌"
        print(f"  {icon} {label}")
        print(f"     repr: {err!r}")
        print(f"     is_retryable: {retryable}")
        print(f"     isinstance(TaskError): {isinstance(err, TaskError)}")
        print()

    # 2. 演示层级捕获
    print("🎯 === 层级捕获 ===")
    try:
        raise ExternalServiceError("Redis 连接超时")
    except TaskRetryableError as exc:
        print(f"  TaskRetryableError 层捕获 ExternalServiceError: {exc}")

    try:
        raise TaskFatalError("数据格式不可修复")
    except TaskError as exc:
        print(f"  TaskError 层捕获 TaskFatalError: {exc}")

    # 3. 演示 raise from 链
    print("\n🔗 === raise ... from ... ===")
    try:
        try:
            raise ConnectionError("Redis connection refused")
        except ConnectionError as original:
            raise ExternalServiceError(
                "Redis 连接失败",
                detail={"host": "localhost", "port": 6379},
            ) from original
    except ExternalServiceError as exc:
        print(f"  caught: {exc!r}")
        print(f"  __cause__: {exc.__cause__}")

    # 4. 非 TaskError 异常
    print("\n⚠️ === 非 TaskError 异常 ===")
    print(f"  is_retryable(ValueError('bad')): {is_retryable(ValueError('bad'))}")
    print(f"  is_retryable(RuntimeError('oops')): {is_retryable(RuntimeError('oops'))}")

    print("\n✅ 异常层级演示完成")


if __name__ == "__main__":
    _demo()
