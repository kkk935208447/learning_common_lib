"""
TaskIQ labels 系统 — 任务元数据标签。

目标:
    演示 TaskIQ labels 系统 — 任务元数据标签

关键概念:
    - labels 是 key-value 元数据，可在中间件中读取
    - 用于路由/优先级/重试配置
    - labels 在 @broker.task() 装饰器中声明

关键 API:
    - @broker.task(queue="high", priority=10) — 通过装饰器附加 labels
    - message.labels                          — 在中间件中读取 labels

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/02_task_definition

运行方式:
    Worker:
        taskiq worker examples.02_task_definition.02_task_labels:broker
    Client:
        python examples/02_task_definition/02_task_labels.py

预期现象:
    - Client 打印每个任务的 labels 配置
    - Worker 控制台显示任务执行日志

生产提醒:
    - labels 的 value 建议统一使用字符串类型，便于序列化和中间件处理
    - 自定义 labels 需配合中间件才能生效（如路由、优先级调度）

技术要点:
    - labels 是 TaskIQ 的元数据机制，类比 Celery 的 task options
    - @broker.task() 中除 task_name 外的关键字参数都会成为 labels
    - 中间件通过 message.labels 字典读取这些元数据
"""

from __future__ import annotations

import asyncio
import os

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from taskiq.serializers import JSONSerializer

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:02_task_definition:02_task_labels",
)

# ── 1. 创建 Broker + ResultBackend ──
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url="redis://default:123456@localhost:6379/1",
        result_ex_time=3600,
        serializer=JSONSerializer()   # taskiq 默认使用的 PickleSerializer序列化，这在 redis 侧是人类不可读的，所以这里使用 JSONSerializer
    )
)

# ── 2. 任务定义：使用 queue label 路由 ──
# queue label 常用于将任务路由到不同的 Worker 队列


@broker.task(
    task_name="examples.02_task_definition.02_task_labels.send_notification",
    queue="default",
)
async def send_notification(user_id: int, message: str) -> dict:
    """发送通知（默认队列）。"""
    print(f"📦 [default 队列] 发送通知给用户 {user_id}: {message}")
    return {"user_id": user_id, "status": "sent"}


@broker.task(
    task_name="examples.02_task_definition.02_task_labels.process_payment",
    queue="high",
)
async def process_payment(order_id: str, amount: float) -> dict:
    """处理支付（高优先级队列）。"""
    print(f"📦 [high 队列] 处理支付: order={order_id}, amount={amount}")
    return {"order_id": order_id, "amount": amount, "status": "paid"}


# ── 3. 任务定义：使用 priority label ──
# priority label 可被自定义中间件读取，实现优先级调度


@broker.task(
    task_name="examples.02_task_definition.02_task_labels.send_email",
    queue="default",
    priority="10",
)
async def send_email(to: str, subject: str) -> dict:
    """发送邮件（优先级 10，较高）。"""
    print(f"📦 [priority=10] 发送邮件: to={to}, subject={subject}")
    return {"to": to, "subject": subject, "status": "sent"}


@broker.task(
    task_name="examples.02_task_definition.02_task_labels.generate_report",
    queue="default",
    priority="1",
)
async def generate_report(report_type: str) -> dict:
    """生成报表（优先级 1，较低）。"""
    print(f"📦 [priority=1] 生成报表: type={report_type}")
    return {"report_type": report_type, "status": "generated"}


# ── 4. 任务定义：自定义 labels ──
# 任意 key-value 都可以作为 labels，供中间件读取


@broker.task(
    task_name="order:process",
    queue="high",
    priority="10",
    max_retries="3",
    retry_delay="5",
    timeout="300",
    owner="payment-team",
)
async def process_order(order_id: str, items: list[str]) -> dict:
    """处理订单（多个自定义 labels）。"""
    print(f"📦 [多标签任务] 处理订单: order={order_id}, items={items}")
    return {"order_id": order_id, "item_count": len(items), "status": "processed"}


# ── 5. 客户端发送任务并展示 labels ──


async def main() -> None:
    """演示：发送带 labels 的任务，展示 labels 配置。"""
    await broker.startup()
    try:
        print("🚀 TaskIQ Labels 系统演示")
        print("=" * 60)
        print()

        # 展示每个任务的 labels
        tasks = [
            ("send_notification", send_notification),
            ("process_payment", process_payment),
            ("send_email", send_email),
            ("generate_report", generate_report),
            ("process_order", process_order),
        ]

        for name, task in tasks:
            print(f"📋 {name}")
            print(f"   task_name = {task.task_name}")
            print(f"   labels    = {task.labels}")
            print()

        # 发送任务并获取结果
        print("── 发送任务 ──")
        print()

        handle = await send_notification.kiq(user_id=42, message="你好!")
        result = await handle.wait_result(timeout=10)
        print(f"✅ send_notification → {result.return_value}")

        handle = await process_payment.kiq(order_id="ORD-001", amount=99.9)
        result = await handle.wait_result(timeout=10)
        print(f"✅ process_payment  → {result.return_value}")

        handle = await process_order.kiq(order_id="ORD-002", items=["手机", "耳机"])
        result = await handle.wait_result(timeout=10)
        print(f"✅ process_order    → {result.return_value}")
        print()

        print("💡 提示:")
        print("   - labels 本身不会改变任务行为，需要配合中间件才能生效")
        print("   - 中间件通过 message.labels['queue'] 读取路由信息")
        print("   - 中间件通过 message.labels['priority'] 实现优先级调度")
        print("   - 详见 05_middlewares 目录的中间件示例")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
