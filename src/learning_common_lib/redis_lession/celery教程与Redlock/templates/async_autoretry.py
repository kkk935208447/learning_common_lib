"""
解决什么问题: 为 `custom aio pool + async def task` 提供 await 期间可用的自动重试装饰器
输入输出约定: 仅用于 `@app.task(bind=True)` 修饰过的 async Celery 任务；返回值保持原任务返回值不变
失败策略: 命中 `autoretry_for` 的异常自动转成 `self.retry()`；命中 `dont_autoretry_for` 或其他异常原样抛出
不适用场景: 同步任务；已经在任务体内显式 `self.retry()` 的场景；不使用 Celery Task `self` 的普通协程
"""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar

from celery import Task
from celery.exceptions import Ignore, Retry
from celery.utils.time import get_exponential_backoff_interval

P = ParamSpec("P")
R = TypeVar("R")
_MISSING = object()


def async_autoretry(
    *,
    autoretry_for: tuple[type[Exception], ...],
    dont_autoretry_for: tuple[type[Exception], ...] = (),
    retry_kwargs: dict[str, Any] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """为 bind=True 的 async Celery 任务补上 await 期间的自动重试。"""
    if not autoretry_for:
        raise ValueError("autoretry_for 不能为空")

    retry_kwargs_template = dict(retry_kwargs or {})

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@async_autoretry 只支持 async def 任务")

        @wraps(func)
        async def wrapper(self: Task, *args: P.args, **kwargs: P.kwargs) -> R:
            if not isinstance(self, Task):
                raise TypeError("@async_autoretry 要求任务声明为 @app.task(bind=True)")

            retry_call_kwargs = dict(getattr(self, "retry_kwargs", {}) or {})
            retry_call_kwargs.update(retry_kwargs_template)

            try:
                return await func(self, *args, **kwargs)
            except Ignore:  # 不可恢复（直接丢弃）
                raise
            except Retry:
                raise
            except dont_autoretry_for:
                raise
            except autoretry_for as exc:
                retry_backoff = float(getattr(self, "retry_backoff", False))
                if retry_backoff:
                    retry_call_kwargs["countdown"] = get_exponential_backoff_interval(
                        factor=int(max(1.0, retry_backoff)),
                        retries=self.request.retries,
                        maximum=int(getattr(self, "retry_backoff_max", 600)),
                        full_jitter=bool(getattr(self, "retry_jitter", True)),
                    )
                # 刪除 override_max_retries 防止对其他任务造成影响
                previous_override_max_retries = getattr(
                    self,
                    "override_max_retries",
                    _MISSING,
                )
                if previous_override_max_retries is not _MISSING:
                    retry_call_kwargs.setdefault("max_retries", previous_override_max_retries)

                try:
                    ret = self.retry(exc=exc, **retry_call_kwargs)
                finally:
                    if previous_override_max_retries is _MISSING:
                        if hasattr(self, "override_max_retries"):
                            delattr(self, "override_max_retries")
                    else:
                        self.override_max_retries = previous_override_max_retries
                raise ret

        return wrapper

    return decorator


__all__ = ["async_autoretry"]
