"""
目标: 演示手写重试装饰器配合 ExternalServiceError 和 RateLimitedError，展示 Retry-After 退避逻辑
关键 API: functools.wraps, time.sleep, random (jitter)
Python 版本: 3.11+
运行命令: uv run python examples/10_retry_and_idempotency/01_retry_with_backoff.py  (从 exception教程/ 目录)
预期现象: 展示指数退避重试、Retry-After 退避、不可重试异常直接抛出
生产提醒: 生产环境建议用 tenacity 库；本示例展示原理，保持零依赖
"""

from __future__ import annotations

import functools
import random
import time
from dataclasses import dataclass


# ============================================================
# 异常定义
# ============================================================

@dataclass
class ExternalServiceError(Exception):
    """外部服务调用失败（可重试）。"""
    message: str = "外部服务不可用"
    service: str = "unknown"

    def __str__(self) -> str:
        return f"[{self.service}] {self.message}"


@dataclass
class RateLimitedError(Exception):
    """触发限流（可重试，需遵守 Retry-After）。"""
    message: str = "请求被限流"
    retry_after: float = 1.0  # 秒

    def __str__(self) -> str:
        return f"{self.message} (retry_after={self.retry_after}s)"


class AuthError(Exception):
    """认证失败（不可重试）。"""
    pass



# ============================================================
# 重试装饰器
# ============================================================

def retry(
    max_attempts: int = 3,
    retryable: tuple[type[Exception], ...] = (ExternalServiceError,),
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    jitter: bool = True,
):
    """指数退避重试装饰器（tenacity 风格，零依赖）。

    特殊处理:
      - RateLimitedError: 使用 retry_after 字段作为等待时间
      - 其他 retryable 异常: 指数退避 + 可选 jitter
      - 非 retryable 异常: 直接抛出，不重试
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except RateLimitedError as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    wait = e.retry_after
                    print(f"  [重试] 第 {attempt}/{max_attempts} 次失败: {e}")
                    print(f"         遵守 Retry-After，等待 {wait:.2f}s")
                    time.sleep(wait)
                except retryable as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    # 指数退避: base_delay * 2^(attempt-1)
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay *= random.uniform(0.5, 1.5)
                    print(f"  [重试] 第 {attempt}/{max_attempts} 次失败: {e}")
                    print(f"         指数退避，等待 {delay:.2f}s")
                    time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator



# ============================================================
# 模拟外部服务
# ============================================================

class FlakyPaymentGateway:
    """模拟不稳定的支付网关。"""

    def __init__(self) -> None:
        self._call_count = 0

    def charge(self, order_id: str, amount: float) -> dict:
        """模拟支付：前 2 次失败，第 3 次成功。"""
        self._call_count += 1
        if self._call_count <= 2:
            raise ExternalServiceError(
                message=f"订单 {order_id} 支付超时",
                service="payment-gateway",
            )
        return {"order_id": order_id, "amount": amount, "status": "paid"}


class RateLimitedAPI:
    """模拟有限流的 API。"""

    def __init__(self) -> None:
        self._call_count = 0

    def fetch(self, resource: str) -> dict:
        """模拟 API 调用：第 1 次限流，第 2 次成功。"""
        self._call_count += 1
        if self._call_count <= 1:
            raise RateLimitedError(
                message=f"获取 {resource} 被限流",
                retry_after=0.2,  # 演示用短时间
            )
        return {"resource": resource, "data": "ok"}


# ============================================================
# 演示
# ============================================================

def demo_exponential_backoff() -> None:
    """演示 1：指数退避重试。"""
    print("=" * 60)
    print("演示 1：指数退避重试 — ExternalServiceError")
    print("=" * 60)

    gateway = FlakyPaymentGateway()

    @retry(max_attempts=3, retryable=(ExternalServiceError,), base_delay=0.05)
    def pay(order_id: str) -> dict:
        return gateway.charge(order_id, 99.9)

    result = pay("ORD-001")
    print(f"  最终成功: {result}")


def demo_retry_after() -> None:
    """演示 2：Retry-After 退避。"""
    print(f"\n{'=' * 60}")
    print("演示 2：Retry-After 退避 — RateLimitedError")
    print("=" * 60)

    api = RateLimitedAPI()

    @retry(max_attempts=3, retryable=(ExternalServiceError, RateLimitedError), base_delay=0.05)
    def fetch(resource: str) -> dict:
        return api.fetch(resource)

    result = fetch("users/42")
    print(f"  最终成功: {result}")


def demo_non_retryable() -> None:
    """演示 3：不可重试异常直接抛出。"""
    print(f"\n{'=' * 60}")
    print("演示 3：不可重试异常 — AuthError 直接抛出，不重试")
    print("=" * 60)

    @retry(max_attempts=3, retryable=(ExternalServiceError,), base_delay=0.05)
    def call_with_bad_token() -> dict:
        raise AuthError("token 已过期")

    try:
        call_with_bad_token()
    except AuthError as e:
        print(f"  AuthError 直接抛出（未重试）: {e}")


if __name__ == "__main__":
    demo_exponential_backoff()
    demo_retry_after()
    demo_non_retryable()

    print(f"\n{'=' * 60}")
    print("重试与退避要点")
    print("=" * 60)
    print("""
  1. 只重试「可重试」异常（网络超时、限流），认证失败等不可重试
  2. 指数退避: delay = base_delay * 2^(attempt-1)，加 jitter 避免惊群
  3. RateLimitedError 携带 retry_after 字段，重试时遵守服务端要求
  4. 设置 max_attempts 上限，避免无限重试
  5. 生产环境建议用 tenacity 库:
     @tenacity.retry(
         stop=stop_after_attempt(3),
         wait=wait_exponential(min=0.1, max=10),
         retry=retry_if_exception_type(ExternalServiceError),
     )
""")
