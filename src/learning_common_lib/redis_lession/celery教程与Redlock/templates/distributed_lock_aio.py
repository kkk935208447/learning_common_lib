"""
解决什么问题: 为分布式部署的多个服务实例提供基于单 Redis 的纯异步分布式锁，
    在长临界区内通过 asyncio 看门狗自动续期，避免锁 TTL 提前耗尽导致互斥失效
输入输出约定: async_distributed_lock / AsyncRedisWatchdogLock 作为 async 上下文管理器使用；
    @with_async_lock 只是可选语法糖（如 "order:{order_id}"）
失败策略: 获取锁超时抛出 LockAcquireError（可重试异常），由 BaseTask 或调用方决定重试
不适用场景: 单进程内协程互斥优先用 asyncio.Lock；需要多主 Redis 容错时应考虑多实例方案；
    持锁逻辑仍应尽量短，看门狗只是兜底，不鼓励超长临界区
实现边界: 全程使用 redis.asyncio + asyncio；续期逻辑运行在事件循环内，
    不依赖后台线程；单 Redis 仍然是可用性与一致性的单点

锁的三种使用方式:
  1. async_distributed_lock()     — async-first 主路径，首选
  2. AsyncRedisWatchdogLock(...)  — 显式对象，适合需要调试或监控内部状态
  3. @with_async_lock(...)        — 补充语法糖，只在重复样板很多时再启用

注意：
  - 业务传入的是逻辑锁名，如 "order:12345"；Redis 中真实 key 统一为 "lock:{name}"
  - 本模块是异步代码路径下的推荐实现；同步代码仍使用 templates/distributed_lock.py
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Callable, TypeVar

import redis.asyncio as aioredis      # 引入异步 Redis 底座
from redis.asyncio.lock import Lock   # 引入异步锁

try:
    from .error_handling import LockAcquireError
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.error_handling import LockAcquireError  # type: ignore[no-redef]

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


# 控制模块向外导出的边界
__all__ = [
    "AsyncRedisWatchdogLock",
    "LockAcquireError",
    "async_distributed_lock",
    "with_async_lock",
]


def _lock_key(name: str) -> str:
    return f"lock:{name}"


def _format_pttl(pttl_ms: int) -> str:
    if pttl_ms == -2:
        return "key 不存在"
    if pttl_ms == -1:
        return "无过期时间"
    return f"{pttl_ms / 1000:.2f}s"


def _validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0，当前值为 {value!r}")


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} 不能小于 0，当前值为 {value!r}")


def _resolve_renew_interval(timeout: float, renew_interval: float | None) -> float:
    """
    解析并验证锁的续期间隔，默认续期间隔设置为 timeout 的 2/3，确保在锁过期前完成续期操作
    """
    if renew_interval is None:
        return timeout * 2 / 3
    if renew_interval >= timeout:
        raise ValueError(
            f"renew_interval 必须小于 timeout，当前 renew_interval={renew_interval!r}, timeout={timeout!r}"
        )
    _validate_positive("renew_interval", renew_interval)
    return renew_interval


def _build_lock(
    redis_client: aioredis.Redis,     # 异步 redis 底座
    name: str,                        # 锁名称，建议用业务前缀如 "order:12345"
    timeout: float,                   # 锁的基础过期时间（秒）
    blocking_timeout: float,          # 获取锁的最大等待时间（秒）
) -> Lock:
    return redis_client.lock(
        _lock_key(name),
        timeout=timeout,
        blocking_timeout=blocking_timeout,
    )


def _log_release_exception(
    *,
    name: str,                  # 锁名称，建议用业务前缀如 "order:12345"
    timeout: float,             # 锁的基础过期时间（秒）
    auto_renewal: bool,         # 是否开启后台自动续期，看门狗机制
    boundary: str,
    exc: Exception,
) -> None:
    logger.warning(
        "异步分布式锁释放异常，已忽略并继续返回: lock_name=%s boundary=%s exc_type=%s exc=%s",
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


def _resolve_redis_client(arguments: dict[str, Any], redis_attr: str) -> aioredis.Redis:
    if "redis_client" in arguments:
        return arguments["redis_client"]

    first_arg = next(iter(arguments.values()), None)
    if first_arg is not None and hasattr(first_arg, redis_attr):
        return getattr(first_arg, redis_attr)

    raise LockAcquireError(
        f"无法获取 Redis 客户端: 参数中没有 'redis_client'，"
        f"第一个参数也没有 '{redis_attr}' 属性",
    )


class AsyncRedisWatchdogLock:
    """纯异步 Redis 分布式锁，带 asyncio 看门狗续期。

    特性:
      1. 使用 redis.asyncio，不阻塞事件循环
      2. 看门狗在事件循环中续期，无后台线程
      3. release() / __aexit__() 使用 shield，尽量避免 cancel 打断释放
      4. Redis 中真实 key 统一为 lock:{name}，便于观测 TTL 与排障
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,              # 异步 Redis 底座
        name: str,                                 # 锁名称，建议用业务前缀如 "order:12345"
        timeout: float = 30.0,                     # 锁的基础过期时间（秒）
        blocking_timeout: float = 5.0,             # 获取锁的最大等待时间（秒）
        auto_renewal: bool = True,                 # 是否开启后台自动续期，看门狗机制
        renew_interval: float | None = None,       # 看门狗间隔（秒）
        max_watchdog_failures: int = 3,            # 看门狗失败最大次数
    ) -> None:
        _validate_positive("timeout", timeout)
        _validate_non_negative("blocking_timeout", blocking_timeout)
        if max_watchdog_failures < 1:
            raise ValueError("max_watchdog_failures 至少为 1")

        self.redis = redis_client
        self.name = name
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.auto_renewal = auto_renewal
        self.renew_interval = _resolve_renew_interval(timeout, renew_interval)
        self.max_watchdog_failures = max_watchdog_failures

        self._lock: Lock | None = None  # 当前 Redis 分布式锁对象；未获取时为 None
        self._watchdog_task: asyncio.Task[None] | None = None  # 看门狗续期协程任务；未启动为 None
        self._watchdog_stop = asyncio.Event()  # 看门狗停止信号；释放/清理时会触发（set）
        self._owner_task: asyncio.Task[Any] | None = None  # 绑定当前持锁的 owner task，用于兜底清理
        self._owner_done_cleanup_task: asyncio.Task[None] | None = None  # owner 结束后的清理任务，避免“永生锁”
        self._acquired = False     # 是否已经成功 acquire 这把锁

    @property
    def redis_key(self) -> str:
        return _lock_key(self.name)

    @property
    def acquired(self) -> bool:
        return self._acquired

    async def acquire(self) -> bool:
        """获取锁，成功后按需启动看门狗。"""
        if self._acquired:
            raise RuntimeError(f"锁已处于持有状态，不可重复 acquire: {self.name}")

        self._watchdog_stop = asyncio.Event()
        self._lock = _build_lock(
            self.redis,
            self.name,
            timeout=self.timeout,
            blocking_timeout=self.blocking_timeout,
        )
        acquired = await self._lock.acquire(
            blocking=True,
            blocking_timeout=self.blocking_timeout,
        )
        if not acquired:
            return False

        self._acquired = True
        # 把锁显式绑定到当前 owner task；如果调用方忘记 release，
        # 后面的 done callback 会负责兜底清理，避免 watchdog 单独把锁续期成“永生锁”。
        self._bind_owner_task()
        if self.auto_renewal:
            self._watchdog_task = asyncio.create_task(
                self._watchdog_loop(),
                name=f"redis-watchdog:{self.redis_key}",
            )
            logger.debug(
                "异步分布式锁看门狗已启动",
                extra={
                    "lock_name": self.name,
                    "lock_key": self.redis_key,
                    "renew_interval": self.renew_interval,
                },
            )
        return True

    async def release(self) -> None:
        """先停看门狗，再释放锁。

        释放阶段若锁已过期、所有权不匹配或 Redis 短暂异常，只记录日志，不再向业务层二次抛错。
        """
        self._unbind_owner_task()
        await self._stop_watchdog()

        lock = self._lock
        if not self._acquired or lock is None:
            return

        try:
            await lock.release()
        except Exception as exc:
            _log_release_exception(
                name=self.name,
                timeout=self.timeout,
                auto_renewal=self.auto_renewal,
                boundary="async_context_manager",
                exc=exc,
            )
        finally:
            self._acquired = False
            self._lock = None

    async def pttl(self) -> int:
        """读取当前锁 key 的剩余 TTL（毫秒）。"""
        return await self.redis.pttl(self.redis_key)

    def _bind_owner_task(self) -> None:
        """把锁绑定到获取它的 asyncio Task，防止 owner task 意外结束后 watchdog 继续无限续期。"""
        owner_task = asyncio.current_task()
        self._owner_task = owner_task
        if owner_task is not None:
            owner_task.add_done_callback(self._on_owner_task_done)

    def _unbind_owner_task(self) -> None:
        owner_task = self._owner_task
        if owner_task is not None and not owner_task.done():
            owner_task.remove_done_callback(self._on_owner_task_done)
        self._owner_task = None

    def _on_owner_task_done(self, task: asyncio.Task[Any]) -> None:
        """owner task 结束但锁仍未显式释放时，触发兜底清理。"""
        if not self._acquired:
            return

        reason = self._describe_owner_done_reason(task)
        self._schedule_owner_done_cleanup(reason)

    def _describe_owner_done_reason(self, task: asyncio.Task[Any]) -> str:
        """把 owner task 的结束原因转成日志友好的短字符串。"""
        if task.cancelled():    # 任务被撤销
            return "cancelled"

        exc = task.exception()
        if exc is None:
            return "finished_without_release"
        return type(exc).__name__

    def _schedule_owner_done_cleanup(self, reason: str) -> None:
        """把 owner-done 兜底释放调度成独立 task，避免把 await 链塞进回调函数。"""
        try:
            self._owner_done_cleanup_task = asyncio.create_task(
                self._release_after_owner_done(reason),
                name=f"redis-lock-owner-cleanup:{self.redis_key}",
            )
        except RuntimeError:
            logger.error(
                "owner task 已结束，但事件循环无法创建清理任务，锁将依赖 TTL 自然过期: lock_name=%s",
                self.name,
                extra={
                    "lock_name": self.name,
                    "lock_key": self.redis_key,
                    "owner_done_reason": reason,
                },
            )

    async def _release_after_owner_done(self, reason: str) -> None:
        try:
            if not self._acquired:
                return

            logger.warning(
                "owner task 已结束但锁仍未释放，开始执行兜底释放: lock_name=%s reason=%s",
                self.name,
                reason,
                extra={
                    "lock_name": self.name,
                    "lock_key": self.redis_key,
                    "owner_done_reason": reason,
                },
            )
            # cleanup task 自己也可能被取消；这里再加一层 shield，
            # 尽量保证真实的 release() 不被外层取消链打断。
            await asyncio.shield(self.release())
        finally:
            self._owner_done_cleanup_task = None

    async def __aenter__(self) -> AsyncRedisWatchdogLock:
        acquired = await self.acquire()
        if not acquired:
            raise LockAcquireError(
                f"获取锁失败: {self.name}",
                detail={
                    "lock_name": self.name,
                    "lock_key": self.redis_key,
                    "timeout": self.timeout,
                    "blocking_timeout": self.blocking_timeout,
                    "auto_renewal": self.auto_renewal,
                    "renew_interval": self.renew_interval,
                },
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        try:
            await asyncio.shield(self.release())
        except Exception as exc:
            _log_release_exception(
                name=self.name,
                timeout=self.timeout,
                auto_renewal=self.auto_renewal,
                boundary="async_aexit",
                exc=exc,
            )
        return False

    async def _stop_watchdog(self) -> None:
        task = self._watchdog_task
        if task is None:
            return

        self._watchdog_stop.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(
                "异步分布式锁看门狗退出异常，已忽略: lock_name=%s exc_type=%s exc=%s",
                self.name,
                type(exc).__name__,
                exc,
                extra={
                    "lock_name": self.name,
                    "lock_key": self.redis_key,
                    "watchdog_error_type": type(exc).__name__,
                },
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        finally:
            self._watchdog_task = None

    async def _watchdog_loop(self) -> None:
        lock = self._lock
        if lock is None:
            return

        consecutive_failures = 0
        while True:
            try:
                await asyncio.wait_for(
                    self._watchdog_stop.wait(),
                    timeout=self.renew_interval,
                )
                return
            except TimeoutError:
                pass

            try:
                # 尝试续期锁
                await lock.extend(self.timeout, replace_ttl=True)
                if consecutive_failures > 0:
                    logger.info(
                        "异步分布式锁续期恢复正常: lock_name=%s",
                        self.name,
                        extra={
                            "lock_name": self.name,
                            "lock_key": self.redis_key,
                            "renew_interval": self.renew_interval,
                        },
                    )
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "异步分布式锁续期失败 (%d/%d): lock_name=%s exc_type=%s exc=%s",
                    consecutive_failures,
                    self.max_watchdog_failures,
                    self.name,
                    type(exc).__name__,
                    exc,
                    extra={
                        "lock_name": self.name,
                        "lock_key": self.redis_key,
                        "renew_interval": self.renew_interval,
                        "watchdog_failures": consecutive_failures,
                    },
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                if consecutive_failures >= self.max_watchdog_failures:
                    logger.error(
                        "异步分布式锁续期连续失败，放弃续期并等待自然过期: lock_name=%s",
                        self.name,
                        extra={
                            "lock_name": self.name,
                            "lock_key": self.redis_key,
                            "max_watchdog_failures": self.max_watchdog_failures,
                        },
                    )
                    return


@asynccontextmanager
async def async_distributed_lock(
    redis_client: aioredis.Redis,
    name: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
    renew_interval: float | None = None,
    max_watchdog_failures: int = 3,
) -> AsyncGenerator[AsyncRedisWatchdogLock, None]:
    """纯异步分布式锁上下文管理器。

    Args:
        redis_client: redis.asyncio.Redis 实例。
        name: 逻辑锁名称，建议使用业务前缀，如 "order:12345"。
        timeout: 锁的基础过期时间（秒）。
        blocking_timeout: 获取锁的最大等待时间（秒）。
        auto_renewal: 是否开启 asyncio 看门狗自动续期。
        renew_interval: 续期间隔（秒），默认取 timeout 的 2/3。
        max_watchdog_failures: 连续续期失败多少次后放弃续期。

    Raises:
        LockAcquireError: 获取锁超时。

    用法:
        async with async_distributed_lock(redis_client, "order:12345"):
            await process_order(12345)
    """
    lock = AsyncRedisWatchdogLock(
        redis_client=redis_client,
        name=name,
        timeout=timeout,
        blocking_timeout=blocking_timeout,
        auto_renewal=auto_renewal,
        renew_interval=renew_interval,
        max_watchdog_failures=max_watchdog_failures,
    )
    async with lock:
        yield lock


def with_async_lock(
    name_template: str,
    timeout: float = 30.0,
    blocking_timeout: float = 5.0,
    auto_renewal: bool = True,
    renew_interval: float | None = None,
    max_watchdog_failures: int = 3,
    redis_attr: str = "redis_client",
) -> Callable[[F], F]:
    """纯异步分布式锁装饰器，支持动态锁名。

    这是对 async_distributed_lock() 的语法糖；主路径仍推荐显式写出锁边界。
    """

    def decorator(func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("@with_async_lock 只能装饰 async def 函数")

        sig = inspect.signature(func)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            lock_name = name_template.format(**bound.arguments)
            redis_client = _resolve_redis_client(bound.arguments, redis_attr)
            async with async_distributed_lock(
                redis_client,
                lock_name,
                timeout=timeout,
                blocking_timeout=blocking_timeout,
                auto_renewal=auto_renewal,
                renew_interval=renew_interval,
                max_watchdog_failures=max_watchdog_failures,
            ):
                return await func(*args, **kwargs)

        return async_wrapper  # type: ignore[return-value]

    return decorator


def _demo() -> None:
    """演示：基于 redis.asyncio 的纯异步看门狗分布式锁。"""
    import redis.asyncio as redis

    print("🔒 === 纯异步单 Redis 分布式锁演示（asyncio watchdog） ===\n")

    async def amain() -> None:
        redis_client = redis.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=2,
            decode_responses=True,
        )
        try:
            await redis_client.ping()
            print("✅ Redis 连接成功\n")
        except Exception as exc:
            print(f"❌ Redis 连接失败: {exc}")
            print("请确保 Redis 运行在 localhost:6379，密码为 123456")
            return

        print("📌 方式一: async_distributed_lock() 上下文管理器 + TTL 可视化")
        resource_name = "order:12345"
        redis_key = _lock_key(resource_name)

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
                ttl_ms = await redis_client.pttl(redis_key)
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
        print("  🔓 锁已释放\n")

        print("📌 方式二: 获取锁失败 → LockAcquireError")
        held_lock = AsyncRedisWatchdogLock(
            redis_client,
            "order:conflict",
            timeout=30,
            auto_renewal=False,
        )
        await held_lock.acquire()
        try:
            try:
                async with async_distributed_lock(
                    redis_client,
                    "order:conflict",
                    timeout=5,
                    blocking_timeout=1,
                    auto_renewal=True,
                ):
                    pass
            except LockAcquireError as exc:
                print(f"  ❌ 捕获 LockAcquireError: {exc}")
                print(f"  detail: {exc.detail}")
        finally:
            await held_lock.release()

        print("\n📌 方式三: @with_async_lock 装饰器（作为补充语法糖）")

        class OrderService:
            def __init__(self, client: aioredis.Redis) -> None:
                self.redis_client = client

            @with_async_lock("order:{order_id}", timeout=15, auto_renewal=True)
            async def process_order(self, order_id: str) -> dict[str, str]:
                await asyncio.sleep(0.05)
                print(f"  📦 async 临界区: 处理订单 {order_id}")
                return {"order_id": order_id, "status": "done"}

        svc = OrderService(redis_client)
        print(f"  结果: {await svc.process_order('ORD-999')}\n")

        await redis_client.aclose()
        print("✅ 纯异步单 Redis 分布式锁演示完成")

    asyncio.run(amain())


if __name__ == "__main__":
    _demo()
