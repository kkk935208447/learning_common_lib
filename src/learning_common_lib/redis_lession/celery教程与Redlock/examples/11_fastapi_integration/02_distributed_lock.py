"""
目标: 对比固定 TTL 锁在短任务与长任务中的表现 (Fixed TTL Lock Comparison)
关键概念:
  - 单 Redis 锁已经可以保护分布式部署的多个服务实例
  - 短任务 + 固定 TTL 通常够用
  - 长任务超过 TTL 后，即使业务没做完，也可能已经失锁
关键 API: redis.lock.Lock, acquire(), release(), timeout, blocking_timeout
运行方式:
  Client: python examples/11_fastapi_integration/02_distributed_lock.py
预期现象:
  - 基础获取/释放和竞争互斥都能正常工作
  - 固定 TTL 在短任务下表现正常
  - 同样的固定 TTL 放到长任务里，会出现“任务仍在跑，但别人已经能拿到锁”
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import redis

redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


def print_section(title: str) -> None:
    print(f"── {title} ──")


def clear_demo_keys() -> None:
    for key in redis_client.keys("demo:*"):
        redis_client.delete(key)


async def run_fixed_ttl_scenario(
    *,
    label: str,
    timeout: int,
    work_seconds: int,
    probe_after: int,
) -> dict[str, Any]:
    lock_name = f"demo:{label}"

    def holder() -> dict[str, Any]:
        lock = redis_client.lock(lock_name, timeout=timeout, thread_local=False)
        acquired = lock.acquire(blocking=True, blocking_timeout=1)
        if not acquired:
            return {"holder_acquired": False}

        print(f"  持有者: 获取锁成功 -> {lock_name}, timeout={timeout}s, work={work_seconds}s")
        time.sleep(work_seconds)
        try:
            lock.release()
            print("  持有者: 正常释放锁")
            release_status = "released"
        except redis.exceptions.LockError as exc:
            print(f"  持有者: 释放失败，说明锁已不属于自己 -> {type(exc).__name__}")
            release_status = type(exc).__name__
        return {"holder_acquired": True, "release_status": release_status}

    holder_future = asyncio.create_task(asyncio.to_thread(holder))
    await asyncio.sleep(probe_after)

    probe = redis_client.lock(lock_name, timeout=timeout, thread_local=False)
    probe_acquired = await asyncio.to_thread(probe.acquire, blocking=False)
    print(f"  探测者: 在第 {probe_after}s 时尝试获取同一把锁 -> {probe_acquired}")
    if probe_acquired:
        await asyncio.to_thread(probe.release)
        print("  探测者: 释放自己拿到的锁")

    holder_info = await holder_future
    return {
        "label": label,
        "timeout": timeout,
        "work_seconds": work_seconds,
        "probe_after": probe_after,
        "probe_acquired_midway": probe_acquired,
        **holder_info,
    }


async def main() -> None:
    print("🚀 固定 TTL 分布式锁对比示例\n")
    clear_demo_keys()

    print_section("场景 A: 基础获取 / 释放")
    lock = redis_client.lock("demo:basic_lock", timeout=10)
    acquired = lock.acquire(blocking=False)
    print(f"  ✅ 获取锁: {acquired}")
    print(f"  ✅ 锁存在: {bool(redis_client.exists('demo:basic_lock'))}")
    lock.release()
    print(f"  ✅ 释放后仍存在: {bool(redis_client.exists('demo:basic_lock'))}\n")

    print_section("场景 B: 竞争互斥")
    lock_a = redis_client.lock("demo:competition", timeout=10)
    lock_b = redis_client.lock("demo:competition", timeout=10)
    lock_a.acquire(blocking=False)
    print("  Worker A: acquired=True")
    print(f"  Worker B: acquired={lock_b.acquire(blocking=False)}")
    lock_a.release()
    print(f"  Worker B 再次尝试: acquired={lock_b.acquire(blocking=False)}")
    lock_b.release()
    print("  结论: 同一时刻只有一个持有者。\n")

    print_section("场景 C: 固定 TTL 放在短任务里，通常是够用的")
    short_case = await run_fixed_ttl_scenario(
        label="short-task-ok",
        timeout=5,
        work_seconds=2,
        probe_after=1,
    )
    print(f"  ✅ {short_case}")
    print("  结论: 任务完成时间短于 TTL 时，固定 TTL 锁没有问题。\n")

    print_section("场景 D: 固定 TTL 放在长任务里，会出现中途失锁")
    long_case = await run_fixed_ttl_scenario(
        label="long-task-risk",
        timeout=3,
        work_seconds=6,
        probe_after=4,
    )
    print(f"  ✅ {long_case}")
    print("  结论: 原任务还在执行，但探测者已经能拿到锁，这就是长任务的固定 TTL 风险。\n")

    print_section("最终总结")
    rows = [
        ("短任务 + TTL", "通常够用", "业务完成前锁不会过期"),
        ("长任务 + TTL", "存在风险", "任务没做完，锁可能已经失效"),
        ("下一步", "需要看门狗", "让锁在长任务期间持续续期"),
    ]
    for label, value, note in rows:
        print(f"  {label:<14} {value:<10} {note}")

    clear_demo_keys()
    redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
