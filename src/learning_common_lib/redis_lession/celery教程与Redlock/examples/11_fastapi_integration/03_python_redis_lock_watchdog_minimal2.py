"""
目标: AsyncRedisWatchdogLock / async_distributed_lock 的若干集成案例（需本地 Redis）
关键概念:
  - 与 `templates/distributed_lock_aio.py` 配套，验证异步锁、互斥、超时失败、看门狗续期
  - 使用 `redis.asyncio`，与其它示例共用 host/port/password/db
关键 API: async_distributed_lock, AsyncRedisWatchdogLock, LockAcquireError, pttl()
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/11_fastapi_integration
运行方式:
  Client:
    python examples/11_fastapi_integration/05_distributed_lock_aio_cases.py
预期现象:
  - 案例 1：持锁期间 key 存在，退出后释放
  - 案例 2：两个协程串行通过同一把锁（第二个会等待）
  - 案例 3：锁被占用且 blocking 时间过短时抛出 LockAcquireError
  - 案例 4：开启看门狗时，长时间持锁下 PTTL 会被周期性拉回（不会一直掉到 0）
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import redis.asyncio as aioredis

try:
    from ...templates.distributed_lock_aio import (
        AsyncRedisWatchdogLock,
        LockAcquireError,
        async_distributed_lock,
    )
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.distributed_lock_aio import (  # type: ignore[no-redef]
        AsyncRedisWatchdogLock,
        LockAcquireError,
        async_distributed_lock,
    )

REDIS_KWARGS: dict[str, Any] = {
    "host": "localhost",
    "port": 6379,
    "password": "123456",
    "db": 2,
    "decode_responses": True,
}

# 与其它示例区分，统一前缀避免误删无关 key
KEY_PREFIX = "demo:aio:lock_cases"


def print_section(title: str) -> None:
    print(f"── {title} ──")


async def pttl_ms(r: aioredis.Redis, lock_name: str) -> int:
    return await r.pttl(lock_name)


async def delete_if_any(r: aioredis.Redis, *names: str) -> None:
    if names:
        await r.delete(*names)


# --------------------------------------------------------------------------- #
# 案例 1：基本 async with，退出后锁应释放
# --------------------------------------------------------------------------- #


async def case_basic_acquire_release(r: aioredis.Redis) -> None:
    name = f"{KEY_PREFIX}:basic"
    await delete_if_any(r, name)

    async with async_distributed_lock(
        r,
        name,
        timeout=10.0,
        blocking_timeout=2.0,
        auto_renewal=False,
    ):
        ms = await pttl_ms(r, name)
        assert ms > 0, "持锁时应有 TTL"
        print(f"  持锁中 PTTL ≈ {ms} ms")

    after = await pttl_ms(r, name)
    # 释放后 key 可能已被删（-2）或极短窗口内仍存在
    assert after in (-2, -1) or after == 0, f"释放后期望无有效 TTL，实际 PTTL={after}"
    print("  [OK] 案例 1：获取 / 释放正常")


# --------------------------------------------------------------------------- #
# 案例 2：同连接上两协程竞争同一把锁 → 第二个等待后进入
# --------------------------------------------------------------------------- #


async def case_two_coroutines_mutex(r: aioredis.Redis) -> None:
    name = f"{KEY_PREFIX}:mutex"
    await delete_if_any(r, name)

    order: list[int] = []

    async def first() -> None:
        async with async_distributed_lock(
            r,
            name,
            timeout=15.0,
            blocking_timeout=5.0,
            auto_renewal=False,
        ):
            order.append(1)
            await asyncio.sleep(0.35)

    async def second() -> None:
        await asyncio.sleep(0.05)
        async with async_distributed_lock(
            r,
            name,
            timeout=15.0,
            blocking_timeout=5.0,
            auto_renewal=False,
        ):
            order.append(2)

    await asyncio.gather(first(), second())
    assert order == [1, 2], f"应先完成 first 再 second，实际顺序={order}"
    print("  [OK] 案例 2：互斥 + 阻塞等待顺序正确")


# --------------------------------------------------------------------------- #
# 案例 3：另一连接长期占锁 → 本连接短时 blocking → LockAcquireError
# --------------------------------------------------------------------------- #


async def case_acquire_timeout_raises(r_holder: aioredis.Redis, r_waiter: aioredis.Redis) -> None:
    name = f"{KEY_PREFIX}:busy"
    await delete_if_any(r_holder, name)

    lock = AsyncRedisWatchdogLock(
        r_holder,
        name,
        timeout=60.0,
        blocking_timeout=2.0,
        auto_renewal=False,
    )
    await lock.acquire()
    try:
        t0 = time.perf_counter()
        try:
            async with async_distributed_lock(
                r_waiter,
                name,
                timeout=60.0,
                blocking_timeout=0.35,
                auto_renewal=False,
            ):
                pass
        except LockAcquireError as e:
            elapsed = time.perf_counter() - t0
            assert "获取锁失败" in str(e)
            assert 0.25 <= elapsed <= 1.2, f"应在 blocking 窗口附近失败，耗时 {elapsed:.2f}s"
            print(f"  捕获 LockAcquireError（耗时 {elapsed:.2f}s，符合预期）")
        else:
            raise AssertionError("应抛出 LockAcquireError")
    finally:
        await lock.release()

    print("  [OK] 案例 3：抢锁超时抛出 LockAcquireError")


# --------------------------------------------------------------------------- #
# 案例 4：看门狗续期 — 持锁时间 > 初始 TTL，PTTL 应被拉回
# --------------------------------------------------------------------------- #


async def case_watchdog_renews_ttl(r: aioredis.Redis) -> None:
    name = f"{KEY_PREFIX}:watchdog"
    await delete_if_any(r, name)

    ttl_sec = 2.0
    renew_interval = ttl_sec * 2 / 3  # 与类默认值一致
    hold_sec = renew_interval + ttl_sec + 0.3  # 至少经历一次续期

    samples: list[tuple[float, int]] = []

    async with async_distributed_lock(
        r,
        name,
        timeout=ttl_sec,
        blocking_timeout=2.0,
        auto_renewal=True,
        renew_interval=renew_interval,
        max_watchdog_failures=3,
    ):
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < hold_sec:
            samples.append((time.perf_counter() - t_start, await pttl_ms(r, name)))
            await asyncio.sleep(0.4)

    # 持锁期间应始终有正 TTL；且若采样跨过续期点，应出现 PTTL 相对前一次“回升”
    positive = [ms for _, ms in samples if ms > 0]
    assert positive, "看门狗场景下持锁期间应能读到正 PTTL"

    bumped = False
    for i in range(1, len(samples)):
        prev_ms = samples[i - 1][1]
        cur_ms = samples[i][1]
        if prev_ms > 0 and cur_ms > 0 and cur_ms > prev_ms + 200:
            bumped = True
            break
    assert bumped, f"预期至少一次续期导致 PTTL 回升，采样: {samples[:8]}..."
    print(f"  采样点数={len(samples)}，已观察到续期导致的 TTL 回升")
    print("  [OK] 案例 4：看门狗续期行为符合预期")


# --------------------------------------------------------------------------- #


async def amain() -> None:
    print_section("distributed_lock_aio 集成案例（需 Redis 可连）")
    r = aioredis.Redis(**REDIS_KWARGS)
    r2 = aioredis.Redis(**REDIS_KWARGS)
    try:
        await r.ping()
    except Exception as exc:
        print(f"无法连接 Redis ({REDIS_KWARGS['host']}:{REDIS_KWARGS['port']}): {exc}")
        raise SystemExit(1) from exc

    try:
        print_section("案例 1：基本获取与释放")
        await case_basic_acquire_release(r)

        print_section("案例 2：两协程互斥")
        await case_two_coroutines_mutex(r)

        print_section("案例 3：阻塞超时 → LockAcquireError")
        await case_acquire_timeout_raises(r, r2)

        print_section("案例 4：看门狗续期")
        await case_watchdog_renews_ttl(r)

        print_section("全部案例通过")
    finally:
        await r.aclose()
        await r2.aclose()


if __name__ == "__main__":
    asyncio.run(amain())
