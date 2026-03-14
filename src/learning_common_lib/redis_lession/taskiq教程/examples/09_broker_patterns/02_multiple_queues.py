"""
TaskIQ 多队列路由 — 通过 labels 的 queue 字段路由任务到不同队列。

目标:
    演示通过 labels 的 queue 字段路由任务到不同队列

关键概念:
    - 通过 @broker.task(queue="high") 指定任务默认队列
    - 通过 kicker().with_labels(queue="urgent").kiq() 动态路由
    - 多 worker 进程监听不同队列

关键 API:
    - @broker.task(queue="...")                    — 指定任务默认队列
    - task.kicker().with_labels(queue="...").kiq() — 动态路由到指定队列
    - taskiq worker ... -fsd "queue_name"          — worker 监听指定队列

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/09_broker_patterns

运行方式:
    Worker 1:
        taskiq worker examples.09_broker_patterns.02_multiple_queues:broker -fsd "default"
    Worker 2:
        taskiq worker examples.09_broker_patterns.02_multiple_queues:broker -fsd "high_priority"
    Client:
        python examples/09_broker_patterns/02_multiple_queues.py

预期现象:
    - default_task 被 Worker 1 消费（default 队列）
    - high_priority_task 被 Worker 2 消费（high_priority 队列）
    - 动态路由的任务根据指定队列被对应 worker 消费

生产提醒:
    - 不同优先级的任务路由到不同队列，配合不同数量的 worker 实现资源隔离
    - 批处理任务建议路由到独立队列，避免阻塞高优先级任务

技术要点:
    - 对比 Celery 的 -Q 参数：TaskIQ 通过 labels 中的 queue 字段路由
    - 不同优先级的任务可以路由到不同队列
    - 多 worker 实例可以监听不同队列实现资源隔离
"""

from __future__ import annotations

import asyncio

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)


# ── 2. 定义不同队列的任务 ──


@broker.task
async def default_task(message: str) -> dict:
    """默认队列任务 — 不指定 queue，走 default 队列。"""
    print(f"📦 [default] 处理消息: {message}")
    return {"queue": "default", "message": message, "status": "done"}


@broker.task(queue="high_priority")
async def high_priority_task(order_id: int) -> dict:
    """高优先级任务 — 路由到 high_priority 队列。"""
    print(f"🔥 [high_priority] 紧急处理订单: order_id={order_id}")
    return {"queue": "high_priority", "order_id": order_id, "status": "done"}


@broker.task(queue="batch")
async def batch_task(batch_id: str, count: int) -> dict:
    """批处理任务 — 路由到 batch 队列，避免阻塞高优先级任务。"""
    print(f"📊 [batch] 批量处理: batch_id={batch_id}, count={count}")
    return {"queue": "batch", "batch_id": batch_id, "count": count, "status": "done"}


# ── 3. 客户端发送任务 ──


async def main() -> None:
    """演示：多队列路由 — 静态声明 + 动态路由。"""
    await broker.startup()

    # ── 3a. 发送到默认队列 ──
    print("=" * 60)
    print("📋 发送任务到不同队列")
    print("=" * 60)
    print()

    print("🚀 [1] 发送到 default 队列（未指定 queue）")
    h1 = await default_task.kiq(message="普通消息处理")
    print(f"   task_id = {h1.task_id}")
    print()

    # ── 3b. 发送到 high_priority 队列 ──
    print("🚀 [2] 发送到 high_priority 队列（装饰器声明）")
    h2 = await high_priority_task.kiq(order_id=9001)
    print(f"   task_id = {h2.task_id}")
    print()

    # ── 3c. 发送到 batch 队列 ──
    print("🚀 [3] 发送到 batch 队列（装饰器声明）")
    h3 = await batch_task.kiq(batch_id="B-2024-001", count=500)
    print(f"   task_id = {h3.task_id}")
    print()

    # ── 3d. 动态路由 — kicker 覆盖队列 ──
    print("🚀 [4] 动态路由 — 将 default_task 临时路由到 high_priority 队列")
    h4 = await (
        default_task.kicker()
        .with_labels(queue="high_priority")
        .kiq(message="紧急消息，动态提升优先级")
    )
    print(f"   task_id = {h4.task_id}")
    print()

    # ── 3e. Worker 启动命令 ──
    print("=" * 60)
    print("🖥️ 多 Worker 启动命令（每个 worker 监听不同队列）")
    print("=" * 60)
    print()
    print("  # Worker 1 — 监听 default 队列")
    print('  taskiq worker examples.09_broker_patterns.02_multiple_queues:broker -fsd "default"')
    print()
    print("  # Worker 2 — 监听 high_priority 队列（可部署更多实例）")
    print('  taskiq worker examples.09_broker_patterns.02_multiple_queues:broker -fsd "high_priority"')
    print()
    print("  # Worker 3 — 监听 batch 队列（低优先级，少量实例）")
    print('  taskiq worker examples.09_broker_patterns.02_multiple_queues:broker -fsd "batch"')
    print()

    # ── 3f. 队列隔离优势 ──
    print("=" * 60)
    print("💡 队列隔离的优势")
    print("=" * 60)
    print("  1. 资源隔离: 批处理不会阻塞高优先级任务")
    print("  2. 弹性伸缩: 高优先级队列可部署更多 worker")
    print("  3. 故障隔离: 某个队列的 worker 挂掉不影响其他队列")
    print("  4. 动态路由: kicker().with_labels(queue=...) 可临时调整优先级")
    print()
    print("💡 对比 Celery:")
    print("  Celery:  celery -A app worker -Q high_priority")
    print("  TaskIQ:  taskiq worker module:broker -fsd \"high_priority\"")

    await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())