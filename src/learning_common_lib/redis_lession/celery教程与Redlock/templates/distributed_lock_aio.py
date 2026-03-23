"""
解决什么问题: 为分布式部署的多个服务实例提供基于单 Redis 的异步分布式锁，并在长临界区内用看门狗自动续期，避免 TTL 提前耗尽导致互斥失效。

输入输出约定: 主入口为 ``async_distributed_lock()`` 与 ``AsyncRedisWatchdogLock``（async with）；锁在 Redis 中的 key 由 ``redis-py`` 的 ``Lock`` 管理，业务只需提供逻辑名 ``name``。

失败策略: 在 ``blocking_timeout`` 内仍无法获取锁时，``__aenter__`` 抛出 ``LockAcquireError``（``detail`` 中带锁名与超时参数，便于重试或告警）；释放阶段若锁已过期或 token 不匹配，会记日志但不向业务层抛异常，以免掩盖原始错误。

不适用场景: 单进程内协程互斥优先用 ``asyncio.Lock``；需要多主 Redis 容错时应考虑 Redlock 等多实例方案；持锁时间仍应尽可能短，看门狗只是缓解而非鼓励超长临界区。

实现边界: 全程 ``redis.asyncio`` + ``asyncio``，续期在事件循环内以 ``Task`` 轮询 ``extend``，无额外线程；``__aexit__`` 用 ``asyncio.shield`` 尽量保证 cancel 时仍能走完释放逻辑。单 Redis 仍是可用性与一致性的单点，与同步版 ``distributed_lock``（python-redis-lock + to_thread）相比，本模块才是异步代码路径下的推荐实现。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.lock import Lock

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 异常定义（与你现有代码保持一致）
# --------------------------------------------------------------------------- #

class LockAcquireError(Exception):
    detail: dict[str, Any]

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


# --------------------------------------------------------------------------- #
# 核心类
# --------------------------------------------------------------------------- #

class AsyncRedisWatchdogLock:
    """生产级异步 Redis 分布式锁，带自动续期看门狗。

    特性：
    - 原生 asyncio，不阻塞事件循环
    - 看门狗自动续期（可选），续期失败连续 N 次后停止并告警
    - __aexit__ 使用 asyncio.shield 保护，防止 cancel 打断释放
    - 参数设计与同步版本完全对齐，便于统一维护

    Args:
        redis_client:     redis.asyncio.Redis 实例
        name:             锁名称
        timeout:          锁的过期时间（秒），默认 30
        blocking_timeout: 等待获取锁的最大时间（秒），默认 5
        auto_renewal:     是否启用看门狗自动续期，默认 True
        renew_interval:   续期间隔（秒），默认 timeout * 2/3
        max_watchdog_failures: 看门狗连续失败多少次后放弃续期，默认 3
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        name: str,
        timeout: float = 30.0,
        blocking_timeout: float = 5.0,
        auto_renewal: bool = True,
        renew_interval: float | None = None,
        max_watchdog_failures: int = 3,
    ) -> None:
        self.redis = redis_client
        self.name = name
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.auto_renewal = auto_renewal
        # 默认续期间隔 = timeout * 2/3
        # 例：timeout=30 → 每 20 秒续期一次，距过期还有 10 秒冗余
        self.renew_interval = renew_interval if renew_interval is not None else timeout * 2 / 3
        self.max_watchdog_failures = max_watchdog_failures

        self._lock: Lock | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._acquired: bool = False

    # ----------------------------------------------------------------------- #
    # 公开接口
    # ----------------------------------------------------------------------- #

    async def acquire(self) -> bool:
        """获取锁，成功后启动看门狗（如已开启 auto_renewal）。"""
        self._lock = self.redis.lock(
            self.name,
            timeout=self.timeout,
            blocking_timeout=self.blocking_timeout,
        )
        self._acquired = await self._lock.acquire(blocking=True)

        if self._acquired and self.auto_renewal:
            self._watchdog_task = asyncio.create_task(
                self._watchdog(),
                name=f"redis-watchdog:{self.name}",  # Task 命名，方便 debug
            )
            logger.debug("看门狗已启动", extra={"lock_name": self.name})

        return self._acquired

    async def release(self) -> None:
        """先停看门狗，再释放锁，保证顺序正确。"""
        await self._stop_watchdog()

        if not self._acquired or self._lock is None:
            return

        try:
            await self._lock.release()
            logger.debug("锁已释放", extra={"lock_name": self.name})
        except Exception as exc:
            # 释放失败常见原因：锁已过期（TTL 耗尽）或 Redis 连接问题
            # 不再 raise，避免掩盖业务异常
            logger.exception(
                "释放锁异常（锁可能已过期）",
                extra={"lock_name": self.name, "error": str(exc)},
            )
        finally:
            self._acquired = False

    # ----------------------------------------------------------------------- #
    # 上下文管理器
    # ----------------------------------------------------------------------- #

    async def __aenter__(self) -> AsyncRedisWatchdogLock:
        acquired = await self.acquire()
        if not acquired:
            raise LockAcquireError(
                f"获取锁失败: {self.name}",
                detail={
                    "lock_name": self.name,
                    "timeout": self.timeout,
                    "blocking_timeout": self.blocking_timeout,
                    "auto_renewal": self.auto_renewal,
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
            # ✅ shield 保护：即使外层 Task 被 cancel，release() 也会跑完
            #    CancelledError 是 BaseException，不会被 except Exception 吞掉
            #    所以 cancel 信号依然能正常向上传播
            await asyncio.shield(self.release())
        except Exception as exc:
            logger.exception(
                "上下文管理器退出时释放锁异常",
                extra={"lock_name": self.name, "error": str(exc)},
            )
        return False  # 不吞掉业务异常

    # ----------------------------------------------------------------------- #
    # 内部实现
    # ----------------------------------------------------------------------- #

    async def _stop_watchdog(self) -> None:
        """取消看门狗 Task，等待其真正结束。"""
        if self._watchdog_task is None or self._watchdog_task.done():
            return

        self._watchdog_task.cancel()
        try:
            await self._watchdog_task
        except asyncio.CancelledError:
            pass  # 正常取消，预期行为
        except Exception as exc:
            logger.warning(
                "停止看门狗时出现异常",
                extra={"lock_name": self.name, "error": str(exc)},
            )
        finally:
            logger.debug("看门狗已停止", extra={"lock_name": self.name})

    async def _watchdog(self) -> None:
        """自动续期循环。

        - 每隔 renew_interval 秒将锁 TTL 重置为 timeout
        - 连续失败 max_watchdog_failures 次后停止续期（让锁自然过期，避免死锁）
        - CancelledError 必须透传，保证 Task.cancel() 能正常工作
        """
        consecutive_failures = 0

        lock = self._lock
        if lock is None:
            return

        while True:
            await asyncio.sleep(self.renew_interval)
            try:
                # replace_ttl=True：直接设置为 timeout，而非在剩余 TTL 上累加
                await lock.extend(self.timeout, replace_ttl=True)
                if consecutive_failures > 0:
                    logger.info(
                        "锁续期恢复正常",
                        extra={"lock_name": self.name},
                    )
                consecutive_failures = 0

            except asyncio.CancelledError:
                # ✅ 必须透传，让 _stop_watchdog 里的 await task 能正常结束
                raise

            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "锁续期失败 (%d/%d): %s",
                    consecutive_failures,
                    self.max_watchdog_failures,
                    exc,
                    extra={"lock_name": self.name},
                )
                if consecutive_failures >= self.max_watchdog_failures:
                    logger.error(
                        "锁续期连续失败 %d 次，放弃续期，锁将自然过期",
                        self.max_watchdog_failures,
                        extra={"lock_name": self.name},
                    )
                    return  # 退出循环，让 TTL 自然倒计时，避免死锁


# --------------------------------------------------------------------------- #
# 函数式封装（与你现有 async_distributed_lock 风格完全一致）
# --------------------------------------------------------------------------- #

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
    """纯异步分布式锁上下文管理器，带自动续期看门狗。

    Example::

        async with async_distributed_lock(redis_client, "order:pay:123") as lock:
            await process_payment()
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


