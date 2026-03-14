"""
TaskIQ 最小可运行示例 — Broker 创建、任务定义、任务发送。

目标:
    演示 TaskIQ 最小可运行示例 — Broker 创建、任务定义、任务发送

关键概念:
    - ListQueueBroker（Redis List 竞争消费）
    - @broker.task 装饰器
    - task.kiq() 异步发送

关键 API:
    - ListQueueBroker          — 基于 Redis List 的消息队列 Broker
    - @broker.task             — 将函数注册为 TaskIQ 任务
    - task.kiq()               — 异步发送任务到 Broker
    - handle.wait_result()     — 等待任务执行结果（需要 result_backend）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/01_broker_and_config

运行方式:
    Worker:
        taskiq worker examples.01_broker_and_config.01_taskiq_hello:broker
    Client:
        python examples/01_broker_and_config/01_taskiq_hello.py

预期现象:
    - Worker 控制台显示任务接收和执行日志
    - Client 显示任务发送成功，打印 TaskiqMessage handle 信息

生产提醒:
    - 生产环境应配置 result_backend 以获取任务结果
    - 没有 result_backend 时，kiq() 只发送任务，无法 wait_result()

技术要点:
    - kiq() 是 TaskIQ 的异步发送方法，类比 Celery 的 delay()
    - TaskIQ 原生 async，无需 asyncio.to_thread 包装
    - 对比 Celery：无需 celery-aio-pool 等 workaround
"""

from __future__ import annotations

import asyncio

from taskiq.exceptions import ResultBackendError
from taskiq_redis import ListQueueBroker

# ── 1. 创建 Broker ──
# ListQueueBroker 使用 Redis List 作为消息队列，多个 Worker 竞争消费（类似 Celery）
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
)

# ── 2. 定义任务 ──
# @broker.task 将异步函数注册为 TaskIQ 任务
# 类比 Celery 的 @app.task，但原生支持 async def


@broker.task
async def add(x: int, y: int) -> int:
    """两数相加 — 最简单的 TaskIQ 任务。"""
    print(f"📦 Worker 收到任务: add({x}, {y})")
    result = x + y
    print(f"✅ 计算完成: {x} + {y} = {result}")
    return result


# ── 3. 客户端发送任务 ──


async def main() -> None:
    """演示：发送任务到 Broker。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("阶段 1: 只配置 Broker，不配置 Result Backend")
        print("=" * 60)
        print("这意味着:")
        print("  1. producer 可以正常把消息放进 Redis")
        print("  2. worker 可以正常消费任务")
        print("  3. client 不能通过 handle.wait_result() 取回返回值")
        print()
        print("🚀 发送任务: add(3, 7)")

        # kiq() = Kick Into Queue，异步发送任务
        # 类比 Celery 的 delay() / apply_async()
        handle = await add.kiq(3, 7)

        print("✅ 任务已发送!")
        print(f"   task_id  = {handle.task_id}")
        print(f"   handle   = {handle!r}")
        print()

        print("阶段 2: 故意尝试 wait_result()，观察失败方式")
        print("⏳ 现在调用 handle.wait_result(timeout=3)")
        try:
            await handle.wait_result(timeout=3)
        except ResultBackendError as exc:
            print("✅ 预期内失败: 当前 broker 没有 result_backend")
            print(f"   异常类型 = {type(exc).__name__}")
            print(f"   异常信息 = {exc}")
        print()
        print("对照结论:")
        print("  - 只要有 broker，任务就能发送")
        print("  - 但没有 result_backend，client 无法拿到返回值")
        print("  - 下一节 02_result_backend.py 会补齐这一块能力")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
