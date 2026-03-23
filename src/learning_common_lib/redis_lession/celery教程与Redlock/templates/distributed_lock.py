"""
解决什么问题: 为分布式部署的多个服务实例提供基于单 Redis 的企业级分布式锁，防止同一资源被并发处理
输入输出约定: distributed_lock / async_distributed_lock 作为上下文管理器使用；
    @with_lock 装饰器只是可选语法糖（如 "order:{order_id}"）
失败策略: 获取锁超时抛出 LockAcquireError（可重试异常），由 BaseTask 自动重试
不适用场景: 单进程内的并发用 threading.Lock 即可；如果业务不希望依赖后台续期线程，
    或持锁逻辑跨系统事务边界太长，仍应拆分更小的临界区
实现边界: python-redis-lock 和底层 redis 客户端本身仍是同步实现；
    async_distributed_lock() 只是通过 asyncio.to_thread(...) 让 async 调用侧不阻塞事件循环，并不等于底层锁实现已经完全 async 化

锁的三种使用方式:
  1. async_distributed_lock()   — async-first 主路径，首选
  2. distributed_lock()         — 同步上下文管理器（兼容同步场景）
  3. @with_lock(name_template)  — 补充语法糖，只在重复样板很多时再启用

注意：在异步代码中 python-redis-lock 看门狗的续期线程与 asyncio 调度器之间存在线程安全隐患，这里只是一种展示，该程序可能会存在锁释放异常。
    对于异步场景，最好使用 纯异步锁
"""

from __future__ import annotations

import asyncio
import threading
import functools
import inspect
import logging
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
logger = logging.getLogger(__name__)


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


def _lock_key(name: str) -> str:
    return f"lock:{name}"


def _format_pttl(pttl_ms: int) -> str:
    if pttl_ms == -2:
        return "key 不存在"
    if pttl_ms == -1:
        return "无过期时间"
    return f"{pttl_ms / 1000:.2f}s"


def _log_release_exception(
    *,
    name: str,
    timeout: float,
    auto_renewal: bool,
    boundary: str,
    exc: Exception,
) -> None:
    """释放阶段不再向业务层抛异常，但要保留排障信息。"""
    logger.warning(
        "分布式锁释放异常，已忽略并继续返回: lock_name=%s boundary=%s exc_type=%s exc=%s",
        name,
        boundary,
        type(exc).__name__,
        exc,
        extra={
            "lock_name": name,
            "lock_key": _lock_key(name),
            "timeout": timeout,
            "auto_renewal": auto_renewal,
            "boundary": boundary,
            "release_error_type": type(exc).__name__,
        },
        exc_info=(type(exc), exc, exc.__traceback__),
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
    注意: 这里的锁实现和 Redis 客户端本身仍是同步的。

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
        except Exception as exc:
            _log_release_exception(
                name=name,
                timeout=timeout,
                auto_renewal=auto_renewal,
                boundary="sync_context_manager",
                exc=exc,
            )


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
    它解决的是"async 调用侧不阻塞事件循环"，不是把底层 Redis 锁客户端变成原生 async。
    注意：在异步代码中 python-redis-lock 看门狗的续期线程与 asyncio 调度器之间存在线程安全隐患，这里只是一种展示，该程序可能会存在锁释放异常。
    对于异步场景，最好使用 纯异步锁
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
            # ✅ shield 保护，防止二次 cancel 打断释放操作
            await asyncio.shield(asyncio.to_thread(lock.release))
        except Exception as exc:
            _log_release_exception(
                name=name,
                timeout=timeout,
                auto_renewal=auto_renewal,
                boundary="async_context_manager",
                exc=exc,
            )


def with_lock(
    name_template: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
    redis_attr: str = "redis_client",
) -> Callable[[F], F]:
    """分布式锁装饰器，支持动态锁名。

    这是对上下文管理器的语法糖；教程和模板主路径仍推荐优先写显式的锁边界。
    """

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
    """演示：基于 python-redis-lock 的 async-first 企业级分布式锁用法。"""
    import redis

    print("🔒 === 企业级单 Redis 分布式锁演示（async-first） ===\n")

    redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2)
    try:
        redis_client.ping()
        print("✅ Redis 连接成功\n")
    except redis.ConnectionError as exc:
        print(f"❌ Redis 连接失败: {exc}")
        print("请确保 Redis 运行在 localhost:6379，密码为 123456")
        return

    print("📌 方式一: async_distributed_lock() 上下文管理器 + TTL 可视化")

    async def run_async_lock_demo() -> None:
        resource_name = "order:12345"
        lock_name = _lock_key(resource_name)

        async def holder() -> None:
            async with async_distributed_lock(
                redis_client,
                resource_name,
                timeout=3,
                auto_renewal=True,
            ):
                print("  📦 async 临界区: 持锁处理订单 12345")
                await asyncio.sleep(4)

        async def monitor() -> None:
            previous_ms: int | None = None
            print("  时间点      剩余 TTL      观察")
            for second in range(5):
                ttl_ms = await asyncio.to_thread(redis_client.pttl, lock_name)
                if ttl_ms > 0 and previous_ms is not None and previous_ms > 0 and ttl_ms > previous_ms + 500:
                    note = "TTL 回升，看门狗已续期"
                elif ttl_ms > 0:
                    note = "锁仍被持有"
                else:
                    note = "锁不存在或已释放"
                print(f"  t={second:>2}s   {_format_pttl(ttl_ms):<12} {note}")
                previous_ms = ttl_ms
                await asyncio.sleep(1)

        await asyncio.gather(holder(), monitor())

    asyncio.run(run_async_lock_demo())
    print("  🔓 锁已释放\n")

    print("📌 方式二: distributed_lock() 同步上下文管理器")

    def run_sync_lock_demo() -> None:
        with distributed_lock(redis_client, "order:sync-1001", timeout=5, auto_renewal=False):
            print("  📦 sync 临界区: 处理同步订单 sync-1001")

    run_sync_lock_demo()
    print("  🔓 锁已释放\n")

    print("📌 方式三: 获取锁失败 → LockAcquireError")

    held_lock = _build_lock(redis_client, "order:conflict", timeout=30, auto_renewal=False)
    held_lock.acquire(blocking=False)
    try:
        async def fail_to_acquire() -> None:
            async with async_distributed_lock(
                redis_client,
                "order:conflict",
                timeout=5,
                blocking_timeout=1,
                auto_renewal=True,
            ):
                pass

        asyncio.run(fail_to_acquire())
    except LockAcquireError as exc:
        print(f"  ❌ 捕获 LockAcquireError: {exc}")
        print(f"  detail: {exc.detail}")
    finally:
        try:
            held_lock.release()
        except Exception:
            pass

    print("\n📌 方式四: @with_lock 装饰器（作为补充语法糖）")

    class OrderService:
        def __init__(self) -> None:
            self.redis_client = redis_client

        @with_lock("order:{order_id}", timeout=15, auto_renewal=True)
        async def process_order(self, order_id: str) -> dict[str, str]:
            await asyncio.sleep(0.05)
            print(f"  📦 async 临界区: 处理订单 {order_id}")
            return {"order_id": order_id, "status": "done"}

    svc = OrderService()
    print(f"  结果: {asyncio.run(svc.process_order('ORD-999'))}\n")

    redis_client.close()
    print("\n✅ async-first 企业级单 Redis 分布式锁演示完成")


if __name__ == "__main__":
    _demo()
