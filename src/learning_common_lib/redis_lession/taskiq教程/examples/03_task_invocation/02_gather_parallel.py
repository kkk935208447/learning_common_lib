"""
TaskIQ 并行任务执行与结果收集 — asyncio.gather 并行等待。

目标:
    演示 TaskIQ 并行任务执行与结果收集

关键概念:
    - 并行发送多个任务
    - 使用 asyncio.gather 收集多个 wait_result
    - 对比 Celery group() + GroupResult.get()

关键 API:
    - asyncio.gather              — 并行等待多个协程
    - handle.wait_result()        — 等待单个任务结果

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/03_task_invocation

运行方式:
    Worker:
        taskiq worker examples.03_task_invocation.02_gather_parallel:broker
    Client:
        python examples/03_task_invocation/02_gather_parallel.py

预期现象:
    - Worker 并行处理 5 个计算任务
    - Client 显示每个任务的返回值和执行耗时，以及总耗时

生产提醒:
    - timeout 参数防止无限等待，生产环境务必设置合理超时
    - 大批量任务建议分批发送，避免瞬间打满 Redis 连接

技术要点:
    - TaskIQ 原生 async，直接用 asyncio.gather 并行等待
    - 无需 Celery 的 group/chord 等复杂原语
    - timeout 参数防止无限等待
"""

from __future__ import annotations

import asyncio
import time

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)


# ── 2. 定义任务 ──


@broker.task
async def compute_task(task_num: int, value: int) -> dict:
    """模拟计算任务 — 短暂 sleep 后返回结果。"""
    print(f"📦 Worker 执行计算任务 #{task_num}, value={value}")
    await asyncio.sleep(0.5)  # 模拟耗时计算
    result = value * value
    print(f"✅ 任务 #{task_num} 完成: {value}² = {result}")
    return {"task_num": task_num, "input": value, "result": result}


# ── 3. 客户端并行发送与收集 ──


async def main() -> None:
    """演示：并行发送 5 个任务，asyncio.gather 收集结果。"""
    await broker.startup()
    try:
        start_time = time.perf_counter()

        # ── 3a. 并行发送 5 个任务 ──
        print("🚀 并行发送 5 个计算任务...")
        handles = [await compute_task.kiq(task_num=i, value=i * 10) for i in range(1, 6)]
        for h in handles:
            print(f"   已发送 task_id={h.task_id}")
        print()

        # ── 3b. asyncio.gather 并行等待所有结果 ──
        print("⏳ 等待所有任务完成...")
        results = await asyncio.gather(
            *[h.wait_result(timeout=30) for h in handles]
        )

        # ── 3c. 打印结果 ──
        print()
        for i, res in enumerate(results, 1):
            print(f"📊 任务 #{i}: 返回值={res.return_value}, 耗时={res.execution_time:.3f}s")

        elapsed = time.perf_counter() - start_time
        print(f"\n⏱️  总耗时: {elapsed:.3f}s（并行执行，远小于串行 5×0.5s=2.5s）")
        print()
        print("💡 对比 Celery:")
        print("   Celery  → group(task.s(i) for i in range(5))().get()")
        print("   TaskIQ  → asyncio.gather(*[h.wait_result() for h in handles])")
        print("   TaskIQ 原生 async，无需 group/chord 等复杂原语")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
