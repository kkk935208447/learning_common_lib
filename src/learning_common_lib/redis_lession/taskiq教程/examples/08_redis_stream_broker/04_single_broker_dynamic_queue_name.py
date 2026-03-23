"""
TaskIQ 单 broker + 动态 queue_name 路由（RedisStreamBroker）细化版。

目标:
    证明三件事：
      1. 一个 RedisStreamBroker 可以同时监听多个 stream
      2. producer 通过 `queue_name` label 可以把任务动态路由到不同 stream
      3. 我们可以直接读取 Redis 的 XLEN 增量，证明消息确实写进了目标 stream

关键概念:
    - 默认 stream 由 broker.queue_name 决定
    - 动态路由依赖 task labels 里的 `queue_name`
    - additional_streams 让一个 worker 入口一次监听多个 stream
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from redis.asyncio import Redis
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

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
    "taskiq:examples:08_redis_stream_broker:04:default",
)
HIGH_PRIORITY_STREAM = os.getenv(
    "TASKIQ_QUEUE_NAME_HIGH_PRIORITY",
    "taskiq:examples:08_redis_stream_broker:04:high_priority",
)
BATCH_STREAM = os.getenv(
    "TASKIQ_QUEUE_NAME_BATCH",
    "taskiq:examples:08_redis_stream_broker:04:batch",
)
CONSUMER_GROUP_NAME = os.getenv(
    "TASKIQ_STREAM_CONSUMER_GROUP",
    "taskiq:examples:08_redis_stream_broker:04",
)


def build_stream_broker() -> RedisStreamBroker:
    result_backend = RedisAsyncResultBackend(
        redis_url=RESULT_BACKEND_URL,
        result_ex_time=3600,
    )
    return RedisStreamBroker(
        url=BROKER_URL,
        queue_name=DEFAULT_STREAM,
        consumer_group_name=CONSUMER_GROUP_NAME,
        additional_streams={
            # 这里的 ">" 不是占位符，而是 Redis XREADGROUP 的特殊游标：
            # 表示“读取这个 consumer group 里尚未投递给任何 consumer 的新消息”。
            # 当前示例要演示的是“像正常队列一样消费 high / batch 的新任务”，
            # 所以这里应该写 ">"，而不是 "0" / "0-0" 之类用于 pending/历史消息的起点。
            HIGH_PRIORITY_STREAM: ">",
            BATCH_STREAM: ">",
        },
        xread_block=1000,
        xread_count=50,
        idle_timeout=30_000,
        unacknowledged_batch_size=100,
        maxlen=1000,
        approximate=True,
    ).with_result_backend(result_backend)


broker = build_stream_broker()


@broker.task(
    task_name="examples.08_redis_stream_broker.04_single_broker_dynamic_queue_name.default_task",
)
async def default_task(message: str) -> dict[str, Any]:
    print(f"📦 [default stream] 处理消息: {message}")
    return {"route": "default", "message": message}


@broker.task(
    task_name="examples.08_redis_stream_broker.04_single_broker_dynamic_queue_name.high_priority_task",
    queue_name=HIGH_PRIORITY_STREAM,
)
async def high_priority_task(order_id: int) -> dict[str, Any]:
    print(f"🔥 [high_priority stream] 紧急处理订单: order_id={order_id}")
    return {"route": "high_priority", "order_id": order_id}


@broker.task(
    task_name="examples.08_redis_stream_broker.04_single_broker_dynamic_queue_name.batch_task",
    queue_name=BATCH_STREAM,
)
async def batch_task(batch_id: str, count: int) -> dict[str, Any]:
    print(f"📊 [batch stream] 批量处理: batch_id={batch_id}, count={count}")
    return {"route": "batch", "batch_id": batch_id, "count": count}


async def get_stream_lengths(redis_conn: Redis) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for stream_name in (DEFAULT_STREAM, HIGH_PRIORITY_STREAM, BATCH_STREAM):
        lengths[stream_name] = await redis_conn.xlen(stream_name) if await redis_conn.exists(stream_name) else 0
    return lengths


def print_delta(title: str, before: dict[str, int], after: dict[str, int]) -> None:
    print(title)
    for stream_name in (DEFAULT_STREAM, HIGH_PRIORITY_STREAM, BATCH_STREAM):
        delta = after[stream_name] - before[stream_name]
        print(f"  {stream_name:<70} delta={delta:+d} total={after[stream_name]}")


async def assert_routed_to_stream(
    *,
    redis_conn: Redis,
    expected_stream: str,
    sender: Any,
    sender_kwargs: dict[str, Any],
) -> None:
    before = await get_stream_lengths(redis_conn)
    handle = await sender.kiq(**sender_kwargs)
    after_send = await get_stream_lengths(redis_conn)

    print_delta("  发送后 stream 长度增量:", before, after_send)

    for stream_name, length in after_send.items():
        delta = length - before[stream_name]
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
            print("=" * 72)
            print("TaskIQ 单 broker + 动态 queue_name 路由（RedisStreamBroker）")
            print("=" * 72)
            print("当前 broker 配置:")
            print(f"  default stream      = {DEFAULT_STREAM}")
            print(f"  high_priority stream= {HIGH_PRIORITY_STREAM}")
            print(f"  batch stream        = {BATCH_STREAM}")
            print(f"  consumer group      = {CONSUMER_GROUP_NAME}")
            print()
            print("证明方式:")
            print("  每次 kiq() 之后立刻读取三个 stream 的 XLEN，")
            print("  用长度增量证明消息确实写进了目标 stream。")
            print()

            print("🚀 [1] 发送默认 stream 任务")
            await assert_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=DEFAULT_STREAM,
                sender=default_task,
                sender_kwargs={"message": "普通消息处理"},
            )
            print()

            print("🚀 [2] 发送 high_priority stream 任务")
            await assert_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=HIGH_PRIORITY_STREAM,
                sender=high_priority_task,
                sender_kwargs={"order_id": 9001},
            )
            print()

            print("🚀 [3] 发送 batch stream 任务")
            await assert_routed_to_stream(
                redis_conn=redis_conn,
                expected_stream=BATCH_STREAM,
                sender=batch_task,
                sender_kwargs={"batch_id": "B-2026-001", "count": 500},
            )
            print()

            print("结论:")
            print("  1. 一个 broker 对象可以通过 queue_name label 写入不同 stream")
            print("  2. XLEN 增量证明消息确实进入了对应 stream")
            print("  3. additional_streams 让一个 worker 入口同时消费多个 stream")


if __name__ == "__main__":
    asyncio.run(main())
