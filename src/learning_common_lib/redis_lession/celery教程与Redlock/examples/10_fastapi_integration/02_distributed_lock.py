"""
目标: 演示单 Redis 分布式锁机制与竞争处理 (Single Redis Distributed Lock & Competition)
关键 API: redis.lock.Lock, acquire(), release(), timeout
运行方式:
  Client: python examples/10_fastapi_integration/02_distributed_lock.py
预期现象: 演示锁获取、释放、超时、竞争等分布式锁核心机制
生产提醒:
  - 服务可以是分布式部署的，锁底座仍然可以是单 Redis
  - 锁超时必须大于任务最大执行时间，使用 db=2 避免与 Celery 冲突
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import redis
from celery import Celery

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.10_fastapi_integration.02_distributed_lock",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

# ── 2. Redis 连接 ──
# 使用 db=2 避免与 Celery broker(db=0) 和 backend(db=1) 冲突
redis_client = redis.Redis(host="localhost", port=6379, password="123456", db=2, decode_responses=True)


# ── 3. Celery 任务 (使用 redis.lock.Lock) ──
@app.task(bind=True)
def process_order_with_lock(self: Any, order_id: str) -> dict[str, str]:
    """使用分布式锁处理订单，防止并发重复处理"""
    lock_name = f"lock:order:{order_id}"
    lock = redis.lock.Lock(redis_client, lock_name, timeout=30)

    if not lock.acquire(blocking=True, blocking_timeout=5):
        return {"order_id": order_id, "status": "skipped", "reason": "无法获取锁"}

    try:
        print(f"  🔒 获取锁成功: {lock_name}")
        time.sleep(1)  # 模拟处理
        print(f"  📦 处理订单: {order_id}")
        return {"order_id": order_id, "status": "completed"}
    finally:
        try:
            lock.release()
            print(f"  🔓 释放锁: {lock_name}")
        except redis.exceptions.LockNotOwnedError:
            print(f"  ⚠️ 锁已过期自动释放: {lock_name}")


# ── 4. 入口 ──
async def main() -> None:
    print("🚀 单 Redis 分布式锁示例 (真实 Redis)\n")

    # 验证 Redis 连接
    print("── 验证 Redis 连接 ──")
    pong = redis_client.ping()
    print(f"  ✅ Redis PING: {pong}\n")

    # Demo 1: 基本锁获取与释放
    print("── 基本锁获取与释放 ──")
    lock = redis_client.lock("demo:basic_lock", timeout=10)
    acquired = lock.acquire(blocking=False)
    print(f"  🔑 获取锁: {acquired}")
    print(f"  🔍 锁存在: {redis_client.exists('demo:basic_lock')}")
    lock.release()
    print(f"  🔓 释放锁")
    print(f"  🔍 锁存在: {redis_client.exists('demo:basic_lock')}")
    print()

    # Demo 2: 锁竞争 — 同一资源只有一个能获取
    print("── 锁竞争 ──")
    lock1 = redis_client.lock("demo:competition", timeout=10)
    lock2 = redis_client.lock("demo:competition", timeout=10)

    lock1.acquire(blocking=False)
    print(f"  🔑 Worker A 获取锁: True")
    result = lock2.acquire(blocking=False)
    print(f"  🔑 Worker B 获取锁: {result}")  # False
    lock1.release()
    print(f"  🔓 Worker A 释放锁")
    result = lock2.acquire(blocking=False)
    print(f"  🔑 Worker B 再次获取锁: {result}")  # True
    lock2.release()
    print()

    # Demo 3: 锁超时自动释放
    print("── 锁超时自动释放 ──")
    lock3 = redis_client.lock("demo:timeout", timeout=2)
    lock3.acquire(blocking=False)
    print(f"  🔑 获取锁 (timeout=2s)")
    print(f"  ⏳ 等待 3 秒...")
    await asyncio.sleep(3)
    print(f"  🔍 锁存在: {redis_client.exists('demo:timeout')}")  # 0, expired
    print()

    # Demo 4: 阻塞等待获取锁
    print("── 阻塞等待获取锁 ──")
    lock4 = redis_client.lock("demo:blocking", timeout=3)
    lock4.acquire(blocking=False)
    print(f"  🔑 锁已被持有")

    async def try_acquire():
        # acquire() 在线程池里执行；关闭 thread_local，避免 release() 时丢失锁 token。
        lock5 = redis_client.lock("demo:blocking", timeout=10, thread_local=False)
        print(f"  ⏳ 等待获取锁 (blocking_timeout=5s)...")
        acquired = await asyncio.to_thread(lock5.acquire, blocking=True, blocking_timeout=5)
        print(f"  🔑 等待后获取锁: {acquired}")
        if acquired:
            try:
                await asyncio.to_thread(lock5.release)
            except redis.exceptions.LockError:
                print("  ⚠️ 等待者已不再持有锁，跳过释放")

    # 2秒后释放锁，让等待者获取
    async def release_later():
        await asyncio.sleep(2)
        try:
            lock4.release()
            print(f"  🔓 原持有者释放锁")
        except Exception:
            pass

    await asyncio.gather(try_acquire(), release_later())
    print()

    # Demo 5: 并发竞争 (ThreadPoolExecutor)
    print("── 并发竞争 (3 个 worker 竞争同一订单锁) ──")
    def compete_for_lock(worker_name: str) -> str:
        lock = redis_client.lock("demo:order:1001", timeout=10, blocking_timeout=2)
        acquired = lock.acquire(blocking=True, blocking_timeout=2)
        if not acquired:
            print(f"  ❌ {worker_name}: 获取锁失败")
            return f"{worker_name}: skipped"
        try:
            print(f"  ✅ {worker_name}: 获取锁成功，处理订单")
            time.sleep(0.5)
            return f"{worker_name}: completed"
        finally:
            try:
                lock.release()
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(compete_for_lock, f"Worker-{i}") for i in range(3)]
        for f in futures:
            print(f"  结果: {f.result()}")
    print()

    # 工程化说明
    print("── 工程化说明 ──")
    print("  📋 本教程主线: 单 Redis 实例 + 多服务实例共享同一把锁")
    print("  📋 这已经是分布式锁，因为互斥对象是分布式部署的多个 worker / service 实例")
    print("  📋 如果你想要更高层封装，可以参考 pottery 一类库，但不属于本教程主线")
    print()

    # 生产实现方式
    print("── 生产实现方式 ──")
    print("  💡 方式一: redis-py Lock (教程基础篇)")
    print("     lock = redis.Redis(...).lock('resource', timeout=30)")
    print("     with lock:")
    print("         do_work()")
    print()
    print("  💡 方式二: 类似 pottery 的高层封装")
    print("     核心目标仍然是把单 Redis 锁包装成更清晰的 API 和异常语义")
    print()
    print("  💡 方式三: Celery 任务去重")
    print("     @app.task(bind=True)")
    print("     def my_task(self, resource_id):")
    print("         lock_key = f'lock:my_task:{resource_id}'")
    print("         if not redis.set(lock_key, self.request.id, nx=True, ex=300):")
    print("             raise Reject('任务已在执行中')")

    # 清理 demo keys
    # ⚠️ KEYS 命令会阻塞 Redis，生产环境应使用 SCAN 替代
    for key in redis_client.keys("demo:*"):
        redis_client.delete(key)


if __name__ == "__main__":
    asyncio.run(main())
