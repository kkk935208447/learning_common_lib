"""
解决什么问题: 为分布式部署的多个服务实例提供基于单 Redis 的企业级分布式锁，防止同一资源被并发处理
输入输出约定: distributed_lock / async_distributed_lock 作为上下文管理器使用；
    @with_lock 装饰器支持动态锁名（如 "order:{order_id}"）
失败策略: 获取锁超时抛出 LockAcquireError（可重试异常），由 BaseTask 自动重试
不适用场景: 单进程内的并发用 threading.Lock 即可；如果业务不希望依赖后台续期线程，
    或持锁逻辑跨系统事务边界太长，仍应拆分更小的临界区

锁的三种使用方式:
  1. distributed_lock()        — 同步上下文管理器
  2. async_distributed_lock()  — 异步包装版上下文管理器
  3. @with_lock(name_template)  — 装饰器，支持动态锁名
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from math import ceil
from typing import Any, Callable, TypeVar

try:
    from .error_handling import LockAcquireError
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_handling import LockAcquireError  # type: ignore[no-redef]

F = TypeVar("F", bound=Callable[..., Any])


def _load_redis_lock_module() -> Any:
    """延迟导入 python-redis-lock，避免缺失依赖时在 import 阶段直接失败。"""
    try:
        import redis_lock
    except ImportError as exc:  # pragma: no cover - 依赖缺失时只在运行期暴露
        raise RuntimeError(
            "缺少依赖 python-redis-lock，请先安装 `python-redis-lock`"
        ) from exc
    return redis_lock


def _normalize_expire(timeout: float) -> int:
    """python-redis-lock 的 expire 更适合使用正整数秒。"""
    return max(1, int(ceil(timeout)))


def _build_lock(
    redis_client: Any,
    name: str,
    timeout: float,
    auto_renewal: bool,
) -> Any:
    redis_lock = _load_redis_lock_module()
    return redis_lock.Lock(
        redis_client,
        name=name,
        expire=_normalize_expire(timeout),
        auto_renewal=auto_renewal,
    )


@contextmanager
def distributed_lock(
    redis_client: Any,
    name: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
) -> Generator[Any, None, None]:
    """同步分布式锁上下文管理器。

    基于 python-redis-lock 实现，适用于"服务是分布式部署的，但锁底座是单 Redis"的场景。
    默认开启 auto_renewal，看门狗线程会在后台自动续期，适合 Celery 长任务。

    Args:
        redis_client: redis.Redis 实例。
        name: 锁名称，建议用业务前缀如 "order:12345"。
        timeout: 锁的基础过期时间（秒）。
        blocking_timeout: 获取锁的最大等待时间（秒）。
        auto_renewal: 是否开启后台自动续期。

    Raises:
        LockAcquireError: 获取锁超时。

    用法:
        with distributed_lock(redis_client, "order:12345"):
            process_order(12345)
    """
    lock = _build_lock(redis_client, name, timeout, auto_renewal=auto_renewal)
    acquired = lock.acquire(blocking=True, timeout=blocking_timeout)
    if not acquired:
        raise LockAcquireError(
            f"获取锁失败: {name}",
            detail={
                "lock_name": name,
                "timeout": timeout,
                "blocking_timeout": blocking_timeout,
                "auto_renewal": auto_renewal,
            },
        )

    try:
        yield lock
    finally:
        try:
            lock.release()
        except Exception:
            # 锁可能已释放或已过期自动回收，忽略释放异常
            pass


@asynccontextmanager
async def async_distributed_lock(
    redis_client: Any,
    name: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
) -> AsyncGenerator[Any, None]:
    """异步分布式锁上下文管理器。

    基于 python-redis-lock 的线程池包装实现，适合在 async 代码中调用同步锁。
    """
    lock = _build_lock(redis_client, name, timeout, auto_renewal=auto_renewal)
    acquired = await asyncio.to_thread(
        lock.acquire,
        blocking=True,
        timeout=blocking_timeout,
    )
    if not acquired:
        raise LockAcquireError(
            f"获取锁失败: {name}",
            detail={
                "lock_name": name,
                "timeout": timeout,
                "blocking_timeout": blocking_timeout,
                "auto_renewal": auto_renewal,
            },
        )

    try:
        yield lock
    finally:
        try:
            await asyncio.to_thread(lock.release)
        except Exception:
            pass


def with_lock(
    name_template: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
    redis_attr: str = "redis_client",
) -> Callable[[F], F]:
    """分布式锁装饰器，支持动态锁名。"""

    def decorator(func: F) -> F:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            lock_name = name_template.format(**bound.arguments)
            redis_client = _resolve_redis_client(bound.arguments, redis_attr)
            with distributed_lock(
                redis_client,
                lock_name,
                timeout,
                blocking_timeout,
                auto_renewal,
            ):
                return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            lock_name = name_template.format(**bound.arguments)
            redis_client = _resolve_redis_client(bound.arguments, redis_attr)
            async with async_distributed_lock(
                redis_client,
                lock_name,
                timeout,
                blocking_timeout,
                auto_renewal,
            ):
                return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _resolve_redis_client(arguments: dict[str, Any], redis_attr: str) -> Any:
    """从函数参数中解析 Redis 客户端。"""
    if "redis_client" in arguments:
        return arguments["redis_client"]

    first_arg = next(iter(arguments.values()), None)
    if first_arg is not None and hasattr(first_arg, redis_attr):
        return getattr(first_arg, redis_attr)

    raise LockAcquireError(
        f"无法获取 Redis 客户端: 参数中没有 'redis_client'，"
        f"第一个参数也没有 '{redis_attr}' 属性",
    )


def _demo() -> None:
    """演示：基于 python-redis-lock 的企业级分布式锁三种使用方式。"""
    import redis

    print("🔒 === 企业级单 Redis 分布式锁演示（python-redis-lock） ===\n")

    redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2)
    try:
        redis_client.ping()
        print("✅ Redis 连接成功\n")
    except redis.ConnectionError as exc:
        print(f"❌ Redis 连接失败: {exc}")
        print("请确保 Redis 运行在 localhost:6379，密码为 123456")
        return

    print("📌 方式一: distributed_lock() 上下文管理器")
    with distributed_lock(redis_client, "order:12345", timeout=10, auto_renewal=True):
        print("  📦 临界区: 处理订单 12345")
    print("  🔓 锁已释放\n")

    print("📌 方式二: @with_lock 装饰器（动态锁名）")

    class OrderService:
        def __init__(self) -> None:
            self.redis_client = redis_client

        @with_lock("order:{order_id}", timeout=15, auto_renewal=True)
        def process_order(self, order_id: str) -> dict[str, str]:
            print(f"  📦 临界区: 处理订单 {order_id}")
            return {"order_id": order_id, "status": "done"}

    svc = OrderService()
    print(f"  结果: {svc.process_order('ORD-999')}\n")

    print("📌 方式三: 获取锁失败 → LockAcquireError")
    held_lock = _build_lock(redis_client, "order:conflict", timeout=30, auto_renewal=False)
    held_lock.acquire(blocking=False)
    try:
        with distributed_lock(
            redis_client,
            "order:conflict",
            timeout=5,
            blocking_timeout=0.1,
            auto_renewal=True,
        ):
            pass
    except LockAcquireError as exc:
        print(f"  ❌ 捕获 LockAcquireError: {exc}")
        print(f"  detail: {exc.detail}")
    finally:
        try:
            held_lock.release()
        except Exception:
            pass

    redis_client.close()
    print("\n✅ 企业级单 Redis 分布式锁演示完成")


if __name__ == "__main__":
    _demo()
