"""
TaskIQ Broker 模式对比 — PubSubBroker 广播 vs ListQueueBroker 竞争消费。

目标:
    演示 PubSubBroker 与 ListQueueBroker 的区别 — 广播 vs 竞争消费

关键概念:
    - PubSubBroker：基于 Redis Pub/Sub，广播模式，所有 worker 都收到消息
    - ListQueueBroker：基于 Redis List，竞争消费，只有一个 worker 处理
    - 选型依据：通知/广播用 PubSub，任务处理用 List

关键 API:
    - PubSubBroker(url=...)            — 基于 Redis Pub/Sub 的广播 Broker
    - ListQueueBroker(url=...)         — 基于 Redis List 的竞争消费 Broker

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/09_broker_patterns

运行方式:
    Worker:
        taskiq worker examples.09_broker_patterns.01_pubsub_broker:list_broker
    Client:
        python examples/09_broker_patterns/01_pubsub_broker.py

预期现象:
    - ListQueueBroker: 多个 worker 中只有一个收到并处理任务
    - PubSubBroker: 所有 worker 都收到消息（广播）
    - Client 打印两种模式的对比表

生产提醒:
    - PubSubBroker 不支持 result_backend（消息是广播的，无法确定哪个 worker 的结果）
    - PubSubBroker 适合事件通知、缓存失效广播等场景
    - 任务队列场景请使用 ListQueueBroker

技术要点:
    - PubSubBroker 不支持 result_backend（消息是广播的，无法确定哪个 worker 的结果）
    - PubSubBroker 适合事件通知、缓存失效广播
    - ListQueueBroker 适合任务队列、工作负载分发
"""

from __future__ import annotations

import asyncio

from taskiq_redis import ListQueueBroker, PubSubBroker, RedisAsyncResultBackend
try:
    from ...templates.taskiq_app import broker_session
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.taskiq_app import broker_session  # type: ignore[no-redef]

# ── 1. 创建两种 Broker ──

# ListQueueBroker — 基于 Redis List，竞争消费模式
# 多个 worker 中只有一个会消费到消息，适合任务队列
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
list_broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)

# PubSubBroker — 基于 Redis Pub/Sub，广播模式
# 所有订阅的 worker 都会收到消息，不支持 result_backend
pubsub_broker = PubSubBroker(
    url="redis://default:123456@localhost:6379/0",
)


# ── 2. 在 ListQueueBroker 上定义任务 ──


@list_broker.task(task_name="examples.09_broker_patterns.01_pubsub_broker.process_order")
async def process_order(order_id: int) -> dict:
    """处理订单 — 竞争消费，只有一个 worker 处理。"""
    print(f"📦 [List] Worker 处理订单: order_id={order_id}")
    result = {"order_id": order_id, "status": "completed", "mode": "list_queue"}
    print(f"✅ [List] 订单处理完成: {result}")
    return result


# ── 3. 在 PubSubBroker 上定义任务 ──


@pubsub_broker.task(task_name="examples.09_broker_patterns.01_pubsub_broker.broadcast_cache_invalidation")
async def broadcast_cache_invalidation(cache_key: str) -> None:
    """广播缓存失效通知 — 所有 worker 都会收到。"""
    print(f"📢 [PubSub] 收到缓存失效广播: cache_key={cache_key}")
    print(f"🗑️ [PubSub] 本地缓存已清除: {cache_key}")


# ── 4. 客户端演示 ──


async def main() -> None:
    """演示：PubSubBroker 广播 vs ListQueueBroker 竞争消费。"""
    async with broker_session(list_broker):
        # ── 4a. ListQueueBroker — 竞争消费 ──
        print("=" * 60)
        print("📋 [ListQueueBroker] 竞争消费模式")
        print("=" * 60)
        print("   底层: Redis LPUSH / BRPOP")
        print("   行为: 多个 worker 中只有一个会消费到消息")
        print("   适用: 任务队列、工作负载分发")
        print()

        handle = await process_order.kiq(order_id=5001)
        print(f"🚀 已发送任务到 ListQueueBroker: task_id={handle.task_id}")

        result = await handle.wait_result(timeout=10)
        print(f"✅ 任务返回值: {result.return_value}")
        print()

        # ── 4b. PubSubBroker — 广播模式 ──
        print("=" * 60)
        print("📡 [PubSubBroker] 广播模式")
        print("=" * 60)
        print("   底层: Redis PUBLISH / SUBSCRIBE")
        print("   行为: 所有订阅的 worker 都会收到消息")
        print("   适用: 事件通知、缓存失效广播")
        print("   限制: 不支持 result_backend（无法确定哪个 worker 的结果）")
        print()
        print("💡 PubSubBroker 广播示例（需要先启动 pubsub worker）:")
        print("   taskiq worker examples.09_broker_patterns.01_pubsub_broker:pubsub_broker")
        print()

        # ── 4c. 对比总结 ──
        print("=" * 60)
        print("📊 两种 Broker 模式对比")
        print("=" * 60)
        print(f"{'特性':<20} {'ListQueueBroker':<20} {'PubSubBroker':<20}")
        print("-" * 60)
        print(f"{'底层机制':<20} {'Redis List':<20} {'Redis Pub/Sub':<20}")
        print(f"{'消费模式':<20} {'竞争消费(1对1)':<20} {'广播(1对多)':<20}")
        print(f"{'result_backend':<20} {'✅ 支持':<20} {'❌ 不支持':<20}")
        print(f"{'消息持久化':<20} {'✅ 持久化':<20} {'❌ 即发即失':<20}")
        print(f"{'适用场景':<20} {'任务队列':<20} {'事件通知/广播':<20}")
        print(f"{'类比':<20} {'Celery worker':<20} {'Redis Pub/Sub':<20}")


if __name__ == "__main__":
    asyncio.run(main())
