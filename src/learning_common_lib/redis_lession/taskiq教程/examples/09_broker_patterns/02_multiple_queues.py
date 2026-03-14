"""
TaskIQ 多队列路由 — 通过多个 broker.queue_name 隔离不同优先级任务。

目标:
    演示 TaskIQ Redis broker 的真实多队列模型

关键概念:
    - taskiq_redis 真正用于路由的是 queue_name
    - 不同队列通常对应不同 broker 对象，而不是一个 broker 靠 CLI 参数切换
    - 不同 worker 分别监听各自 broker.queue_name，实现优先级和资源隔离

关键 API:
    - ListQueueBroker(queue_name="...")    — 指定 Redis 队列名
    - @broker.task                         — 在对应 broker 上注册任务
    - broker_session(...)                  — 同时管理多个 broker 的客户端连接

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/09_broker_patterns

运行方式:
    Worker 1:
        taskiq worker examples.09_broker_patterns.02_multiple_queues:default_broker
    Worker 2:
        taskiq worker examples.09_broker_patterns.02_multiple_queues:high_priority_broker
    Worker 3:
        taskiq worker examples.09_broker_patterns.02_multiple_queues:batch_broker
    Client:
        python examples/09_broker_patterns/02_multiple_queues.py

预期现象:
    - default_task 被 default_broker 对应 worker 消费
    - high_priority_task 被 high_priority_broker 对应 worker 消费
    - batch_task 被 batch_broker 对应 worker 消费

生产提醒:
    - 多队列隔离的核心是“不同队列名 + 不同 worker 部署策略”
    - 高优先级队列可单独扩容 worker 数量
    - CPU/批处理类任务建议独立到单独队列，避免拖慢高优先级路径

技术要点:
    - TaskIQ 没有 Celery 那样的 `-Q` 队列切换参数
    - `--tasks-pattern` / `-fsd` 是任务发现参数，不是队列路由参数
    - 如果要临时改队列，目标 worker 也必须认识该 task_name
"""

from __future__ import annotations

import asyncio

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
try:
    from ...templates.taskiq_app import broker_session
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.taskiq_app import broker_session  # type: ignore[no-redef]

BROKER_URL = "redis://default:123456@localhost:6379/0"
RESULT_BACKEND_URL = "redis://default:123456@localhost:6379/1"


def create_queue_broker(queue_name: str) -> ListQueueBroker:
    """为单个 queue_name 创建专用 broker。"""
    backend = RedisAsyncResultBackend(
        redis_url=RESULT_BACKEND_URL,
        result_ex_time=3600,
    )
    return ListQueueBroker(
        url=BROKER_URL,
        queue_name=queue_name,
    ).with_result_backend(backend)


# ── 1. 为不同队列创建不同 broker ──
default_broker = create_queue_broker("default")
high_priority_broker = create_queue_broker("high_priority")
batch_broker = create_queue_broker("batch")


# ── 2. 在各自的 broker 上注册任务 ──


@default_broker.task(task_name="examples.09_broker_patterns.02_multiple_queues.default_task")
async def default_task(message: str) -> dict:
    """默认队列任务。"""
    print(f"📦 [default] 处理消息: {message}")
    return {"queue_name": "default", "message": message, "status": "done"}


@high_priority_broker.task(task_name="examples.09_broker_patterns.02_multiple_queues.high_priority_task")
async def high_priority_task(order_id: int) -> dict:
    """高优先级任务。"""
    print(f"🔥 [high_priority] 紧急处理订单: order_id={order_id}")
    return {"queue_name": "high_priority", "order_id": order_id, "status": "done"}


@batch_broker.task(task_name="examples.09_broker_patterns.02_multiple_queues.batch_task")
async def batch_task(batch_id: str, count: int) -> dict:
    """批处理任务。"""
    print(f"📊 [batch] 批量处理: batch_id={batch_id}, count={count}")
    return {"queue_name": "batch", "batch_id": batch_id, "count": count, "status": "done"}


# ── 3. 客户端发送任务 ──


async def main() -> None:
    """演示：多队列隔离的真实用法。"""
    async with broker_session(default_broker, high_priority_broker, batch_broker):
        print("=" * 60)
        print("📋 发送任务到不同 queue_name")
        print("=" * 60)
        print("当前 broker -> queue_name 映射:")
        print(f"  default_broker       -> {default_broker.queue_name}")
        print(f"  high_priority_broker -> {high_priority_broker.queue_name}")
        print(f"  batch_broker         -> {batch_broker.queue_name}")
        print()

        print("🚀 [1] 发送到 default 队列")
        h1 = await default_task.kiq(message="普通消息处理")
        r1 = await h1.wait_result(timeout=10)
        print(f"   task_id = {h1.task_id}")
        print(f"   result  = {r1.return_value}")
        print()

        print("🚀 [2] 发送到 high_priority 队列")
        h2 = await high_priority_task.kiq(order_id=9001)
        r2 = await h2.wait_result(timeout=10)
        print(f"   task_id = {h2.task_id}")
        print(f"   result  = {r2.return_value}")
        print()

        print("🚀 [3] 发送到 batch 队列")
        h3 = await batch_task.kiq(batch_id="B-2024-001", count=500)
        r3 = await h3.wait_result(timeout=10)
        print(f"   task_id = {h3.task_id}")
        print(f"   result  = {r3.return_value}")
        print()

        print("=" * 60)
        print("🖥️ 多 Worker 启动命令")
        print("=" * 60)
        print()
        print("  # Worker 1 — 监听 default 队列")
        print("  taskiq worker examples.09_broker_patterns.02_multiple_queues:default_broker")
        print()
        print("  # Worker 2 — 监听 high_priority 队列")
        print("  taskiq worker examples.09_broker_patterns.02_multiple_queues:high_priority_broker")
        print()
        print("  # Worker 3 — 监听 batch 队列")
        print("  taskiq worker examples.09_broker_patterns.02_multiple_queues:batch_broker")
        print()

        print("💡 队列隔离的优势:")
        print("  1. 资源隔离: 批处理不会阻塞高优先级任务")
        print("  2. 弹性伸缩: 高优先级队列可部署更多 worker")
        print("  3. 故障隔离: 某个队列的 worker 挂掉不影响其他队列")
        print("  4. 可观测性更清晰: 每个队列有独立吞吐和积压指标")
        print()
        print("💡 动态路由说明:")
        print("  - TaskIQ Redis 路由读取的是 queue_name，而不是 CLI 上的 -Q 参数")
        print("  - 某个 task 被哪个 worker 消费，取决于它注册在哪个 broker 上")
        print("  - 只有目标 worker 也注册了相同 task_name 时，临时改 queue_name 才能成功消费")
        print()
        print("💡 对比 Celery:")
        print("  Celery:  celery -A app worker -Q high_priority")
        print("  TaskIQ:  为不同 queue_name 创建不同 broker，并分别启动 worker")


if __name__ == "__main__":
    asyncio.run(main())
