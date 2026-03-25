"""
TaskIQ 单 broker + 动态 queue_name 路由（RedisStreamBroker）。

目标:
    给 broker pattern 章节补一条“单 broker + 多 stream”路线，
    并且直接证明任务确实被写进了目标 stream，而不是只看 worker 最终是否执行成功。

关键概念:
    - RedisStreamBroker 发布时会读取 message.labels["queue_name"] 覆盖默认 stream
    - worker 侧通过 additional_streams 一次监听多个 stream
    - 证明路由是否正确，不能只看任务结果，更要直接看 Redis 中各个 stream 的长度增量

运行方式:
    Worker:
        taskiq worker examples.09_broker_patterns.03_single_broker_dynamic_queues_stream:broker
    Client:
        python examples/09_broker_patterns/03_single_broker_dynamic_queues_stream.py
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from redis.asyncio import Redis
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker
from taskiq.serializers import JSONSerializer

try:
    from ...templates.taskiq_app import broker_session
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates.taskiq_app import broker_session  # type: ignore[no-redef]

BROKER_URL = "redis://default:123456@localhost:6379/0"
RESULT_BACKEND_URL = "redis://default:123456@localhost:6379/1"

DEFAULT_STREAM = os.getenv(
    "TASKIQ_QUEUE_NAME_BROKER",
    "taskiq:examples:09_broker_patterns:03_single_broker_dynamic_queues_stream:default",
)
HIGH_PRIORITY_STREAM = os.getenv(
    "TASKIQ_QUEUE_NAME_HIGH_PRIORITY",
    "taskiq:examples:09_broker_patterns:03_single_broker_dynamic_queues_stream:high_priority",
)
BATCH_STREAM = os.getenv(
    "TASKIQ_QUEUE_NAME_BATCH",
    "taskiq:examples:09_broker_patterns:03_single_broker_dynamic_queues_stream:batch",
)
CONSUMER_GROUP_NAME = os.getenv(
    "TASKIQ_STREAM_CONSUMER_GROUP",
    "taskiq:examples:09_broker_patterns:03_single_broker_dynamic_queues_stream",
)


def build_stream_broker() -> RedisStreamBroker:
    # 自动动态路由原理说明:
    # 1. queue_name 为默认 stream。 additional_streams 决定 worker 侧还会额外监听哪些 stream。
    # 2. task 发布时如果 message.labels["queue_name"] 有值，taskiq-redis 会优先把消息写到那个目标 stream，而不是默认 stream。
    # 3. 这正是它和 ListQueueBroker 的关键区别之一：
    #    ListQueueBroker 也支持 producer 侧 queue_name 动态路由，但没有 additional_streams，所以 worker 侧不能像这里一样一次监听多个目标队列。
    return RedisStreamBroker(
        url=BROKER_URL,
        queue_name=DEFAULT_STREAM,   # 默认的 stream 队列名称
        consumer_group_name=CONSUMER_GROUP_NAME,
        additional_streams={
            # 这里的 ">" 直接传给 Redis XREADGROUP：
            # 含义是“从这个 stream 中读取尚未投递给任何 consumer 的新消息”。
            # 当前脚本要证明的是“default / high_priority / batch 都按正常新任务流转”，
            # 所以 additional_streams 应该写 ">"，而不是 "0" / "0-0" 这种偏向 pending/历史消息语义的值。
            HIGH_PRIORITY_STREAM: ">",
            BATCH_STREAM: ">",
        },
        xread_block=1000,
        xread_count=50,
        idle_timeout=30_000,
        unacknowledged_batch_size=100,
        maxlen=1000,
        approximate=True,
    ).with_result_backend(
        RedisAsyncResultBackend(
            redis_url=RESULT_BACKEND_URL,
            result_ex_time=3600,
            serializer=JSONSerializer()   # taskiq 默认使用的 PickleSerializer序列化，这在 redis 侧是人类不可读的，所以这里使用 JSONSerializer
        )
    )


broker = build_stream_broker()


@broker.task(
    task_name="examples.09_broker_patterns.03_single_broker_dynamic_queues_stream.default_task",
)
async def default_task(message: str) -> dict[str, Any]:
    print(f"📦 [default stream] 处理消息: {message}")
    return {"route": "default", "message": message}


@broker.task(
    task_name="examples.09_broker_patterns.03_single_broker_dynamic_queues_stream.high_priority_task",
    queue_name=HIGH_PRIORITY_STREAM,
)
async def high_priority_task(order_id: int) -> dict[str, Any]:
    # 自动动态路由原理:
    # @broker.task(queue_name=...) 并不是让 worker CLI 切队列，而是给这条消息附加 labels["queue_name"]。这里不需要中间件，因为 queue_name 是 broker 实现自己认识的“内建 label”：
    # Taskiq 在发消息时会把 labels 放进 TaskiqMessage / BrokerMessage，然后 RedisStreamBroker.kick() 直接读取 message.labels["queue_name"]。
    # producer 发送时，RedisStreamBroker.kick() 会读取这个 label，然后把消息 XADD 到对应 stream。
    print(f"🔥 [high_priority stream] 紧急处理订单: order_id={order_id}")
    return {"route": "high_priority", "order_id": order_id}


@broker.task(
    task_name="examples.09_broker_patterns.03_single_broker_dynamic_queues_stream.batch_task",
    queue_name=BATCH_STREAM,
)
async def batch_task(batch_id: str, count: int) -> dict[str, Any]:
    print(f"📊 [batch stream] 批量处理: batch_id={batch_id}, count={count}")
    return {"route": "batch", "batch_id": batch_id, "count": count}


async def get_stream_lengths(redis_conn: Redis) -> dict[str, int]:
    """ 获取三个 stream 当前长度"""
    lengths: dict[str, int] = {}
    for stream_name in (DEFAULT_STREAM, HIGH_PRIORITY_STREAM, BATCH_STREAM):
        # Stream 会保留历史消息直到被 trim，所以 XLEN 的“发送前后增量”，可以直接作为“消息写进了哪个 stream”的证据。
        lengths[stream_name] = await redis_conn.xlen(stream_name) if await redis_conn.exists(stream_name) else 0
    return lengths


def print_delta(before: dict[str, int], after: dict[str, int]) -> None:
    """ 打印三个 stream 的长度变化"""
    for stream_name in (DEFAULT_STREAM, HIGH_PRIORITY_STREAM, BATCH_STREAM):
        delta = after[stream_name] - before[stream_name]
        print(f"  {stream_name:<76} delta={delta:+d}")


async def prove_task_routed_to_stream(
    *,
    redis_conn: Redis,
    expected_stream: str,    # 期望消息进入的 stream 名称
    sender: Any,             #  taskiq 任务发送器
    sender_kwargs: dict[str, Any],   # 任务发送器参数
) -> None:
    """ 
    证明某个 sender 发出的消息确实进入了 expected_stream。
    """
    before = await get_stream_lengths(redis_conn)
    handle = await sender.kiq(**sender_kwargs)
    after_send = await get_stream_lengths(redis_conn)

    print("  发送后各 stream 的 XLEN 增量:")
    print_delta(before, after_send)

    # 证明逻辑:
    # 如果某次发送只让“目标 stream”增长 1，而其他 stream 都不变，那么这条消息就确定是被写到了目标 stream。
    for stream_name in (DEFAULT_STREAM, HIGH_PRIORITY_STREAM, BATCH_STREAM):
        delta = after_send[stream_name] - before[stream_name]
        if stream_name == expected_stream:
            assert delta == 1, f"预期 {expected_stream} 增长 1，实际 delta={delta}"
        else:
            assert delta == 0, f"非目标 stream 不应增长: {stream_name}, delta={delta}"

    result = await handle.wait_result(timeout=10)
    print(f"  task_id = {handle.task_id}")
    print(f"  result  = {result.return_value}")


async def main() -> None:
    async with broker_session(broker):
        async with Redis(connection_pool=broker.connection_pool) as redis_conn:
            print("=" * 76)
            print("TaskIQ 单 broker + 动态 queue_name 路由（RedisStreamBroker）")
            print("=" * 76)
            print("当前配置:")
            print(f"  default stream       = {DEFAULT_STREAM}")
            print(f"  high_priority stream = {HIGH_PRIORITY_STREAM}")
            print(f"  batch stream         = {BATCH_STREAM}")
            print(f"  consumer group       = {CONSUMER_GROUP_NAME}")
            print()
            print("证明方法:")
            print("  每次 kiq() 返回后，直接读取 Redis 中三个 stream 的 XLEN。")
            print("  由于 Stream 会保留历史，长度增量能够直接证明消息写进了哪个 stream。")
            print("  worker 之所以也能消费到这些消息，是因为 broker 配置了 additional_streams。")
            print()

            print("🚀 [1] default_task -> default stream")
            await prove_task_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=DEFAULT_STREAM,
                sender=default_task,
                sender_kwargs={"message": "普通消息处理"},
            )
            print()

            print("🚀 [2] high_priority_task -> high_priority stream")
            await prove_task_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=HIGH_PRIORITY_STREAM,
                sender=high_priority_task,
                sender_kwargs={"order_id": 9001},
            )
            print()

            print("🚀 [3] batch_task -> batch stream")
            await prove_task_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=BATCH_STREAM,
                sender=batch_task,
                sender_kwargs={"batch_id": "B-2026-001", "count": 500},
            )
            print()

            print("结论:")
            print("  1. route 正确与否，不再靠猜测 worker 日志，而是直接看 Redis stream 长度增量")
            print("  2. 一个 broker 既可以保留默认 stream，也可以通过 queue_name label 动态路由")
            print("  3. additional_streams 让单 worker 入口可以同时消费多个 stream")


if __name__ == "__main__":
    asyncio.run(main())
