"""
解决什么问题: 提供基于 Redis 的分布式锁（Redlock），防止分布式环境下的并发竞争
输入输出约定: distributed_lock / async_distributed_lock 作为上下文管理器使用；
    @with_lock 装饰器支持动态锁名（如 "order:{order_id}"）
失败策略: 获取锁超时抛出 LockAcquireError（可重试异常），由 BaseTask 自动重试
不适用场景: 单进程内的并发用 threading.Lock 即可；锁持有时间超过 timeout 会自动释放，
    不适合长时间持有锁的场景（应拆分为更小的临界区）

锁的三种使用方式:
  1. distributed_lock()        — 同步上下文管理器
  2. async_distributed_lock()  — 异步上下文管理器
  3. @with_lock(name_template)  — 装饰器，支持动态锁名
"""

from __future__ import annotations

import functools
import inspect
from contextlib import contextmanager, asynccontextmanager
from collections.abc import Generator, AsyncGenerator
from typing import Any, Callable, TypeVar

try:
    from .error_handling import LockAcquireError
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_handling import LockAcquireError  # type: ignore[no-redef]

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# 同步分布式锁
# ---------------------------------------------------------------------------


@contextmanager
def distributed_lock(
    redis_client: Any,
    name: str,
    timeout: float = 10.0,
    blocking_timeout: float = 5.0,
) -> Generator[Any, None, None]:
    """同步分布式锁上下文管理器。

    基于 redis.lock.Lock 实现。

    Args:
        redis_client: redis.Redis 实例。
        name: 锁名称，建议用业务前缀如 "order:12345"。
        timeout: 锁自动释放时间（秒），防止死锁。
        blocking_timeout: 获取锁的最大等待时间（秒）。

    Raises:
        LockAcquireError: 获取锁超时。

    用法:
        with distributed_lock(redis_client, "order:12345"):
            # 临界区
            process_order(12345)
    """
    from redis.lock import Lock
    lock = Lock(redis_client, name, timeout=timeout)

    acquired = lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
    if not acquired:
        raise LockAcquireError(
            f"获取锁失败: {name}",
            detail={"lock_name": name, "timeout": timeout, "blocking_timeout": blocking_timeout},
        )
    try:
        yield lock
    finally:
        try:
            lock.release()
        except Exception:
            # 锁可能已过期自动释放，忽略释放异常
            pass


# ---------------------------------------------------------------------------
# 异步分布式锁
# ---------------------------------------------------------------------------


@asynccontextmanager
async def async_distributed_lock(
    redis_client: Any,
    name: str,
    timeout: float = 10.0,
    blocking_timeout: float = 5.0,
) -> AsyncGenerator[Any, None]:
    """异步分布式锁上下文管理器。

    基于 redis.asyncio.lock.Lock 实现。

    Args:
        redis_client: redis.asyncio.Redis 实例。
        name: 锁名称。
        timeout: 锁自动释放时间（秒）。
        blocking_timeout: 获取锁的最大等待时间（秒）。

    Raises:
        LockAcquireError: 获取锁超时。

    用法:
        async with async_distributed_lock(redis_client, "order:12345"):
            await process_order(12345)
    """
    from redis.asyncio.lock import Lock
    lock = Lock(redis_client, name, timeout=timeout)

    acquired = await lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
    if not acquired:
        raise LockAcquireError(
            f"获取锁失败: {name}",
            detail={"lock_name": name, "timeout": timeout, "blocking_timeout": blocking_timeout},
        )
    try:
        yield lock
    finally:
        try:
            await lock.release()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 装饰器 — 支持动态锁名
# ---------------------------------------------------------------------------


def with_lock(
    name_template: str,
    timeout: float = 10.0,
    blocking_timeout: float = 5.0,
    redis_attr: str = "redis_client",
) -> Callable[[F], F]:
    """分布式锁装饰器，支持动态锁名。

    锁名模板使用函数参数名占位，如 "order:{order_id}"。

    Args:
        name_template: 锁名模板，如 "order:{order_id}"。
        timeout: 锁自动释放时间。
        blocking_timeout: 获取锁等待时间。
        redis_attr: 从第一个参数（通常是 self）获取 Redis 客户端的属性名，
            或者函数参数中名为 "redis_client" 的参数。

    用法:
        @with_lock("order:{order_id}", timeout=15)
        def process_order(self, order_id: str):
            ...  # self.redis_client 会被自动使用
    """
    def decorator(func: F) -> F:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # 绑定参数以解析模板
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            lock_name = name_template.format(**bound.arguments)

            # 获取 redis_client
            rc = _resolve_redis_client(bound.arguments, redis_attr)

            with distributed_lock(rc, lock_name, timeout, blocking_timeout):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            lock_name = name_template.format(**bound.arguments)

            rc = _resolve_redis_client(bound.arguments, redis_attr)

            async with async_distributed_lock(rc, lock_name, timeout, blocking_timeout):
                return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _resolve_redis_client(arguments: dict[str, Any], redis_attr: str) -> Any:
    """从函数参数中解析 Redis 客户端。"""
    # 优先从显式参数 redis_client 获取
    if "redis_client" in arguments:
        return arguments["redis_client"]
    # 其次从第一个参数（self）的属性获取
    first_arg = next(iter(arguments.values()), None)
    if first_arg is not None and hasattr(first_arg, redis_attr):
        return getattr(first_arg, redis_attr)
    raise LockAcquireError(
        f"无法获取 Redis 客户端: 参数中没有 'redis_client'，"
        f"第一个参数也没有 '{redis_attr}' 属性",
    )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


def _demo() -> None:
    """演示：分布式锁的三种使用方式（使用真实 Redis）。

    注意: 需要 Redis 运行在 localhost:6379，密码 123456。
    """
    import redis

    print("🔒 === 分布式锁演示（真实 Redis） ===\n")

    # --- 连接真实 Redis ---
    redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=0)

    try:
        redis_client.ping()
        print("✅ Redis 连接成功\n")
    except redis.ConnectionError as exc:
        print(f"❌ Redis 连接失败: {exc}")
        print("请确保 Redis 运行在 localhost:6379，密码为 123456")
        return

    # 1. 同步上下文管理器
    print("📌 方式一: distributed_lock() 上下文管理器")
    with distributed_lock(redis_client, "order:12345", timeout=10):
        print("  📦 临界区: 处理订单 12345")
    print("  🔓 锁已释放")
    print()

    # 2. @with_lock 装饰器
    print("📌 方式二: @with_lock 装饰器（动态锁名）")

    class OrderService:
        def __init__(self) -> None:
            self.redis_client = redis_client

        @with_lock("order:{order_id}", timeout=15)
        def process_order(self, order_id: str) -> dict:
            print(f"  📦 临界区: 处理订单 {order_id}")
            return {"order_id": order_id, "status": "done"}

    svc = OrderService()
    result = svc.process_order("ORD-999")
    print(f"  结果: {result}")
    print()

    # 3. 演示获取锁失败（blocking_timeout=0 立即超时）
    print("📌 方式三: 获取锁失败 → LockAcquireError")
    # 先占用锁
    from redis.lock import Lock
    held_lock = Lock(redis_client, "order:conflict", timeout=30)
    held_lock.acquire(blocking=False)
    try:
        with distributed_lock(redis_client, "order:conflict", timeout=5, blocking_timeout=0.1):
            pass
    except LockAcquireError as exc:
        print(f"  ❌ 捕获 LockAcquireError: {exc}")
        print(f"  detail: {exc.detail}")
    finally:
        try:
            held_lock.release()
        except Exception:
            pass

    # 清理
    redis_client.close()

    print("\n✅ 分布式锁演示完成")


if __name__ == "__main__":
    _demo()
