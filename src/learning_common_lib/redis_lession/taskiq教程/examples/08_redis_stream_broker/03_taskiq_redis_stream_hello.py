"""
TaskIQ 最小 RedisStreamBroker 示例。

目标:
    在 TaskIQ 里跑通最小的 RedisStreamBroker:
      1. 创建 broker
      2. 绑定 result backend
      3. 定义任务
      4. 发送任务并等待结果

关键概念:
    - RedisStreamBroker 用 Redis Stream + Consumer Group 分发任务
    - 与 ListQueueBroker 相比，它支持 ACK
    - 对 producer 来说，调用方式仍然是 `await task.kiq(...)`

运行方式:
    Worker:
        taskiq worker examples.08_redis_stream_broker.03_taskiq_redis_stream_hello:broker
    Client:
        python examples/08_redis_stream_broker/03_taskiq_redis_stream_hello.py

预期现象:
    - worker 正常处理任务
    - client 能拿到结果
    - stream 与 consumer group 会在 Redis 中自动创建
"""

from __future__ import annotations

import asyncio
import os

from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:08_redis_stream_broker:03:default",
)
CONSUMER_GROUP_NAME = os.getenv(
    "TASKIQ_STREAM_CONSUMER_GROUP",
    "taskiq:examples:08_redis_stream_broker:03",
)

broker = RedisStreamBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
    consumer_group_name=CONSUMER_GROUP_NAME,
    xread_block=1000,
    xread_count=50,
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url="redis://default:123456@localhost:6379/1",
        result_ex_time=3600,
    )
)


@broker.task(task_name="examples.08_redis_stream_broker.03_taskiq_redis_stream_hello.add")
async def add(x: int, y: int) -> int:
    print(f"📦 [stream worker] 收到任务: add({x}, {y})")
    return x + y


async def main() -> None:
    await broker.startup()
    try:
        print("=" * 72)
        print("TaskIQ 最小 RedisStreamBroker 示例")
        print("=" * 72)
        print(f"queue_name          = {QUEUE_NAME}")
        print(f"consumer_group_name = {CONSUMER_GROUP_NAME}")
        print()

        handle = await add.kiq(3, 7)
        result = await handle.wait_result(timeout=10)

        print(f"✅ task_id = {handle.task_id}")
        print(f"✅ result  = {result.return_value}")
        print()
        print("对照理解:")
        print("  - 发送侧 API 和 ListQueueBroker 基本一致")
        print("  - 但底层 broker 已经切到 Redis Stream + Consumer Group")
        print("  - ACK / pending / reclaim 能力是 Stream 版本真正的价值")
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
