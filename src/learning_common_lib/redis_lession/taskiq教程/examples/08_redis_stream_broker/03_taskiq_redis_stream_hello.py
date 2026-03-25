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
        taskiq worker examples.08_redis_stream_broker.03_taskiq_redis_stream_hello:broker --workers 1
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
from taskiq.serializers import JSONSerializer

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
    queue_name=QUEUE_NAME,   # 默认的 stream 队列名称
    consumer_group_name=CONSUMER_GROUP_NAME,   # 消费者组名称
    xread_block=1000,  # 阻塞时间，如果 stream 中没有消息，则阻塞 1000 毫秒
    xread_count=50,  # 读取消息的数量
).with_result_backend(
    RedisAsyncResultBackend(
        redis_url="redis://default:123456@localhost:6379/1",
        result_ex_time=3600,
        serializer=JSONSerializer()   # taskiq 默认使用的 PickleSerializer序列化，这在 redis 侧是人类不可读的，所以这里使用 JSONSerializer
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
