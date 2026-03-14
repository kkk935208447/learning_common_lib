"""
TaskIQ 消息确认控制 — reject 拒绝消息 与 requeue 重新入队。

目标:
    演示 TaskIQ 的消息确认控制 — reject 和 requeue

关键概念:
    - reject() 拒绝消息，不重试（消息从队列移除）
    - requeue() 重新入队，等待下次消费
    - 通过依赖注入获取 Context 对象

关键 API:
    - Context                  — 任务执行上下文，提供 reject/requeue 等控制方法
    - context.reject()         — 拒绝当前消息，消息从队列移除，不再重试
    - context.requeue()        — 将当前消息重新放回队列，等待下次消费
    - TaskiqDepends            — 声明依赖注入（注入 Context）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/06_error_handling

运行方式:
    Worker:
        taskiq worker examples.06_error_handling.01_reject_and_requeue:broker
    Client:
        python examples/06_error_handling/01_reject_and_requeue.py

预期现象:
    - Worker 收到 invalid 场景任务时，调用 reject()，消息被丢弃
    - Worker 收到 unavailable 场景任务时，调用 requeue()，消息重新入队
    - Worker 收到正常任务时，正常处理并返回结果

生产提醒:
    - requeue 可能导致无限循环，建议配合重试计数器使用
    - reject 适用于消息格式错误等不可恢复场景
    - 生产环境建议在 requeue 前加入延迟，避免 CPU 空转

技术要点:
    - reject/requeue 是消息级别的控制，不同于异常重试
    - reject 适用于消息格式错误等不可恢复场景
    - requeue 适用于临时资源不可用等可恢复场景
"""

from __future__ import annotations

import asyncio

from taskiq import Context, TaskiqDepends
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)


# ── 2. 模拟外部资源状态 ──
# 实际场景中可能是数据库连接、第三方 API 等
RESOURCE_AVAILABLE = True


# ── 3. 定义任务（通过 Context 控制消息确认） ──


@broker.task
async def process_order(
    order_data: dict,
    context: Context = TaskiqDepends(),
) -> dict:
    """处理订单 — 演示 reject/requeue 消息控制。

    Context 通过 TaskiqDepends() 自动注入（无需传参），
    提供 reject() 和 requeue() 方法控制消息确认行为。
    """
    order_id = order_data.get("order_id")
    print(f"📦 Worker 收到订单: order_id={order_id}, data={order_data}")

    # 场景 1: 数据校验失败 → reject（消息不可恢复，直接丢弃）
    if not order_id or not isinstance(order_id, int):
        print(f"❌ [reject] 订单数据无效，拒绝消息: {order_data}")
        await context.reject()
        return {"status": "rejected", "reason": "invalid order_id"}

    # 场景 2: 外部资源不可用 → requeue（临时故障，重新入队等待重试）
    if order_data.get("require_gpu") and not RESOURCE_AVAILABLE:
        print(f"🔄 [requeue] GPU 资源不可用，重新入队: order_id={order_id}")
        await context.requeue()
        return {"status": "requeued", "reason": "gpu_unavailable"}

    # 场景 3: 正常处理
    print(f"✅ 订单处理成功: order_id={order_id}")
    return {"status": "completed", "order_id": order_id}


# ── 4. 客户端发送任务 ──


async def main() -> None:
    """演示：发送不同场景的订单任务，观察 reject/requeue 行为。"""
    await broker.startup()
    try:
        # 场景 1: 正常订单
        print("🚀 场景 1 — 发送正常订单")
        handle_ok = await process_order.kiq(order_data={"order_id": 1001, "amount": 99.9})
        print(f"   task_id = {handle_ok.task_id}")
        print()

        # 场景 2: 无效订单（order_id 缺失）→ Worker 端会 reject
        print("🚀 场景 2 — 发送无效订单（缺少 order_id）")
        handle_bad = await process_order.kiq(order_data={"amount": 50.0})
        print(f"   task_id = {handle_bad.task_id}")
        print()

        # 场景 3: 需要 GPU 资源的订单 → Worker 端可能 requeue
        print("🚀 场景 3 — 发送需要 GPU 的订单")
        handle_gpu = await process_order.kiq(
            order_data={"order_id": 1002, "require_gpu": True}
        )
        print(f"   task_id = {handle_gpu.task_id}")
        print()

        print("💡 关键点:")
        print("   - reject/requeue 在 Worker 端执行，Client 端只负责发送")
        print("   - reject(): 消息被丢弃，不再重试（适用于不可恢复错误）")
        print("   - requeue(): 消息重新入队，等待下次消费（适用于临时故障）")
        print("   - Context 通过 TaskiqDepends() 自动注入，无需手动传参")
        print("   - 对比 Celery: Celery 使用 self.retry() 重试，没有 reject/requeue 语义")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
