"""
TaskIQ 两种任务调用方式 — kiq() 快捷调用与 kicker() 高级调用。

目标:
    演示 TaskIQ 的两种任务调用方式 — kiq() 快捷调用与 kicker() 高级调用

关键概念:
    - kiq() 快捷调用（类比 Celery delay()）
    - kicker() 高级调用（类比 Celery apply_async()）
    - kicker 可链式设置 labels、task_id、queue

关键 API:
    - task.kiq()                                    — 快捷发送任务
    - task.kicker()                                 — 获取 AsyncKicker 对象
    - kicker.with_labels(key=value)                 — 附加元数据标签
    - kicker.with_task_id(task_id)                  — 指定自定义 task_id
    - kicker.kiq()                                  — 最终发送任务

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/03_task_invocation

运行方式:
    Worker:
        taskiq worker examples.03_task_invocation.01_kiq_and_kicker:broker
    Client:
        python examples/03_task_invocation/01_kiq_and_kicker.py

预期现象:
    - Worker 控制台显示两次任务执行日志
    - Client 显示 kiq() 和 kicker() 两种方式的发送结果与返回值

生产提醒:
    - with_task_id() 适合幂等场景，用业务 ID 作为 task_id 防止重复提交
    - with_labels() 可配合中间件实现优先级路由、监控打标等

技术要点:
    - kiq() 等价于 kicker().kiq()
    - kicker() 返回 AsyncKicker 对象，支持链式配置
    - with_task_id() 可指定自定义 task_id
    - with_labels() 可附加元数据
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


# ── 2. 定义任务 ──


@broker.task(task_name="examples.03_task_invocation.01_kiq_and_kicker.process_order")
async def process_order(
    order_id: int,
    amount: float,
    context: Context = TaskiqDepends(),
) -> dict:
    """处理订单 — 模拟业务逻辑。"""
    labels = dict(context.message.labels)
    print(f"📦 Worker 处理订单: order_id={order_id}, amount={amount}")
    print(f"   task_id={context.message.task_id}")
    print(f"   labels={labels}")
    result = {
        "order_id": order_id,
        "amount": amount,
        "status": "completed",
        "task_id": context.message.task_id,
        "labels": labels,
    }
    print(f"✅ 订单处理完成: {result}")
    return result


# ── 3. 客户端发送任务 ──


async def main() -> None:
    """演示：kiq() 快捷调用 vs kicker() 高级调用。"""
    await broker.startup()
    try:
        print("=" * 60)
        print("对照目标: kiq() 负责最短路径发送; kicker() 负责先组装再发送")
        print("=" * 60)
        print()

        # ── 3a. kiq() 快捷调用 ──
        # kiq() 等价于 kicker().kiq()，最简方式发送任务
        print("🚀 [方式一] kiq() 快捷调用")
        handle_simple = await process_order.kiq(order_id=1001, amount=99.9)
        print(f"   task_id = {handle_simple.task_id}")
        print("   发送时没有额外 labels，也没有自定义 task_id")

        result_simple = await handle_simple.wait_result(timeout=10)
        print(f"   返回值  = {result_simple.return_value}")
        print()

        # ── 3b. kicker() 高级调用 ──
        print("🚀 [方式二] kicker() 高级调用")
        advanced_kicker = (
            process_order.kicker()
            .with_labels(priority="high", source="api-gateway")
            .with_task_id("custom-123")
        )
        print("   发送前先组装 AsyncKicker:")
        print("     with_labels(priority='high', source='api-gateway')")
        print("     with_task_id('custom-123')")
        handle_advanced = await advanced_kicker.kiq(order_id=2002, amount=199.9)
        print(f"   task_id = {handle_advanced.task_id}")

        result_advanced = await handle_advanced.wait_result(timeout=10)
        print(f"   返回值  = {result_advanced.return_value}")
        print()

        print("对比总结:")
        print("  kiq()")
        print("    - 一步完成发送")
        print("    - 适合大多数普通场景")
        print("    - worker 看到的 labels 通常较少")
        print("  kicker()")
        print("    - 先组装发送参数，再显式 kiq()")
        print("    - 适合补 task_id、labels、路由元数据")
        print("    - 更接近 Celery 的 apply_async() 心智模型")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
