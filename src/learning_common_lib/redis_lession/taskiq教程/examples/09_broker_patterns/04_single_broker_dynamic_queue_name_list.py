"""
TaskIQ 单 broker + 动态 queue_name 路由（ListQueueBroker）。

目标:
    证明三件事：
      1. ListQueueBroker 也支持 producer 侧动态 `queue_name` 路由
      2. 这种路由是 broker 级行为，不依赖 worker 日志猜测
      3. 即便同一个 broker 可以把消息发到多个 list，worker 侧仍然只会监听自身 `queue_name`

关键概念:
    - 本地 `taskiq-redis` 源码中，`ListQueueBroker.kick()` 会优先读取 `message.labels["queue_name"]`
    - 所以 producer 侧确实可以把不同任务写入不同 Redis List
    - 但 `ListQueueBroker.listen()` 只会 `BRPOP(self.queue_name)`，没有 Stream 版 `additional_streams`
    - 因此 List 的动态路由更适合做“发送侧分流”，不能直接等价于 Stream 的“单 worker 多队列消费”

关键 API:
    - `@broker.task(queue_name="...")`     — 给任务附加动态路由 label
    - `RedisAsyncResultBackend(...)`       — 绑定结果后端，保持 broker 形态和正式 producer 一致
    - Redis `LLEN`                         — 观察每个 list 的长度变化
    - Redis `BRPOP`                        — 从目标 list 手动弹出消息
    - `broker.formatter.loads(raw_bytes)`  — 把 broker 消息反序列化回 `TaskiqMessage`

运行方式:
    python examples/09_broker_patterns/04_single_broker_dynamic_queue_name_list.py

预期现象:
    - default / high_priority / batch 三个任务各自只让目标 list 的 LLEN 增加
    - 手动 BRPOP 后可以看到正确的 `task_name` / `labels` / `kwargs`
    - 输出中明确区分“producer 路由已证明”和“worker 侧不能单 broker 多队列监听”
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from redis.asyncio import Redis
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

BROKER_URL = "redis://default:123456@localhost:6379/0"
RESULT_BACKEND_URL = "redis://default:123456@localhost:6379/1"

DEFAULT_QUEUE = os.getenv(
    "TASKIQ_QUEUE_NAME_BROKER",
    "taskiq:examples:09_broker_patterns:04_single_broker_dynamic_queue_name_list:default",
)
HIGH_PRIORITY_QUEUE = os.getenv(
    "TASKIQ_QUEUE_NAME_HIGH_PRIORITY",
    "taskiq:examples:09_broker_patterns:04_single_broker_dynamic_queue_name_list:high_priority",
)
BATCH_QUEUE = os.getenv(
    "TASKIQ_QUEUE_NAME_BATCH",
    "taskiq:examples:09_broker_patterns:04_single_broker_dynamic_queue_name_list:batch",
)


def build_broker() -> ListQueueBroker:
    """创建一个带 result backend 的 ListQueueBroker。

    这里刻意保留 result backend，原因不是本脚本要 `wait_result()`，
    而是让这个 broker 的形态和真实 producer 进程更一致：
    发消息、带 labels、带 result backend，只有“worker 如何消费”这个问题单独拆开讲。
    """
    result_backend = RedisAsyncResultBackend(
        redis_url=RESULT_BACKEND_URL,
        result_ex_time=3600,
    )
    return ListQueueBroker(
        url=BROKER_URL,
        queue_name=DEFAULT_QUEUE,
    ).with_result_backend(result_backend)


broker = build_broker()

# 这里要特别注意：
# ListQueueBroker 只有一个 queue_name，没有 RedisStreamBroker.additional_streams。
# 所以如果直接启动 `taskiq worker xxx:broker`，它只会 BRPOP DEFAULT_QUEUE。
# 本文件证明的是“producer 侧能把消息路由到不同 list”，
# 不是证明“一个 ListQueueBroker worker 可以同时消费多个 list”。


@broker.task(
    task_name="examples.09_broker_patterns.04_single_broker_dynamic_queue_name_list.default_task",
)
async def default_task(message: str) -> dict[str, Any]:
    """默认队列任务。"""
    return {"route": "default", "message": message}


@broker.task(
    task_name="examples.09_broker_patterns.04_single_broker_dynamic_queue_name_list.high_priority_task",
    queue_name=HIGH_PRIORITY_QUEUE,
)
async def high_priority_task(order_id: int) -> dict[str, Any]:
    """高优先级队列任务。"""
    return {"route": "high_priority", "order_id": order_id}


@broker.task(
    task_name="examples.09_broker_patterns.04_single_broker_dynamic_queue_name_list.batch_task",
    queue_name=BATCH_QUEUE,
)
async def batch_task(batch_id: str, count: int) -> dict[str, Any]:
    """批处理队列任务。"""
    return {"route": "batch", "batch_id": batch_id, "count": count}


async def reset_lists(redis_conn: Redis) -> None:
    """清空本脚本使用的三个 list。"""
    await redis_conn.delete(DEFAULT_QUEUE, HIGH_PRIORITY_QUEUE, BATCH_QUEUE)


async def get_queue_lengths(redis_conn: Redis) -> dict[str, int]:
    """读取三个 list 当前长度。"""
    lengths: dict[str, int] = {}
    for queue_name in (DEFAULT_QUEUE, HIGH_PRIORITY_QUEUE, BATCH_QUEUE):
        lengths[queue_name] = await redis_conn.llen(queue_name) if await redis_conn.exists(queue_name) else 0
    return lengths


def print_length_delta(before: dict[str, int], after: dict[str, int]) -> None:
    """打印每个 list 的发送前后长度变化。"""
    for queue_name in (DEFAULT_QUEUE, HIGH_PRIORITY_QUEUE, BATCH_QUEUE):
        delta = after[queue_name] - before[queue_name]
        print(f"  {queue_name:<78} delta={delta:+d}")


async def pop_and_decode(redis_conn: Redis, queue_name: str) -> None:
    """从目标 list 手动弹出消息，并直接反序列化查看内部字段。"""
    popped = await redis_conn.brpop([queue_name], timeout=1)
    assert popped is not None, f"预期能从 {queue_name} 读到消息"

    raw_message = popped[1]
    # 这里用 broker.formatter.loads(...) 反序列化，是为了直接证明：
    # task_name / labels / kwargs 已经真实写进 broker 消息体，
    # 而不是只存在 Python 函数对象的元数据里。
    decoded = broker.formatter.loads(raw_message)

    print(f"  BRPOP queue = {queue_name}")
    print(f"  decoded.task_name = {decoded.task_name}")
    print(f"  decoded.labels    = {decoded.labels}")
    print(f"  decoded.kwargs    = {decoded.kwargs}")


async def prove_task_routed_to_queue(
    *,
    redis_conn: Redis,
    expected_queue: str,
    sender: Any,
    sender_kwargs: dict[str, Any],
) -> None:
    """证明一条任务被写进了预期 list。"""
    before = await get_queue_lengths(redis_conn)
    await sender.kiq(**sender_kwargs)
    after_send = await get_queue_lengths(redis_conn)

    print("  发送后各 list 的 LLEN 增量:")
    print_length_delta(before, after_send)

    # 这里证明的是“producer 侧路由成立”：
    # ListQueueBroker.kick() 会根据 labels["queue_name"] 选择 lpush 到哪个 list。
    # 它不证明“一个 Taskiq worker 就能同时消费这些 list”，
    # 因为 List 模型里 listen() 固定只会 BRPOP(self.queue_name)。
    for queue_name in (DEFAULT_QUEUE, HIGH_PRIORITY_QUEUE, BATCH_QUEUE):
        delta = after_send[queue_name] - before[queue_name]
        if queue_name == expected_queue:
            assert delta == 1, f"预期 {expected_queue} 增长 1，实际 delta={delta}"
        else:
            assert delta == 0, f"非目标 list 不应增长: {queue_name}, delta={delta}"

    await pop_and_decode(redis_conn, expected_queue)
    after_pop = await get_queue_lengths(redis_conn)
    print("  手动 BRPOP 后各 list 的 LLEN:")
    for queue_name in (DEFAULT_QUEUE, HIGH_PRIORITY_QUEUE, BATCH_QUEUE):
        print(f"    {queue_name:<76} len={after_pop[queue_name]}")


async def main() -> None:
    await broker.startup()
    redis_conn = Redis(connection_pool=broker.connection_pool)
    try:
        await reset_lists(redis_conn)

        print("=" * 80)
        print("TaskIQ 单 broker + 动态 queue_name 路由（ListQueueBroker）")
        print("=" * 80)
        print("当前 broker 形态:")
        print(f"  broker.queue_name     = {broker.queue_name}")
        print(f"  broker.result_backend = {broker.result_backend!r}")
        print()
        print("当前队列配置:")
        print(f"  default queue       = {DEFAULT_QUEUE}")
        print(f"  high_priority queue = {HIGH_PRIORITY_QUEUE}")
        print(f"  batch queue         = {BATCH_QUEUE}")
        print()
        print("本地源码结论:")
        print("  ListQueueBroker.kick() 也会优先读取 message.labels['queue_name']")
        print("  所以 producer 侧动态路由是成立的。")
        print()
        print("为什么这里仍然不演示 wait_result():")
        print("  - 当前脚本不启动 Taskiq worker")
        print("  - result backend 已经接好，但没有 worker 执行任务就不会产生结果")
        print("  - 这个脚本关注的是消息到底被 lpush 到了哪个 list")
        print()
        print("为什么这里没有 additional_streams:")
        print("  - 因为 ListQueueBroker 根本没有这个参数")
        print("  - 我们证明的是 producer 侧分流能力，不是 worker 侧多队列监听能力")
        print()
        print("证明方法:")
        print("  1. 发送任务后立刻观察三个 list 的 LLEN 增量")
        print("  2. 从目标 list 手动 BRPOP")
        print("  3. 用 broker.formatter.loads(...) 反序列化，核对 task_name / labels / kwargs")
        print()

        print("🚀 [1] default_task -> default queue")
        await prove_task_routed_to_queue(
            redis_conn=redis_conn,
            expected_queue=DEFAULT_QUEUE,
            sender=default_task,
            sender_kwargs={"message": "普通消息处理"},
        )
        print()

        print("🚀 [2] high_priority_task -> high_priority queue")
        await prove_task_routed_to_queue(
            redis_conn=redis_conn,
            expected_queue=HIGH_PRIORITY_QUEUE,
            sender=high_priority_task,
            sender_kwargs={"order_id": 9001},
        )
        print()

        print("🚀 [3] batch_task -> batch queue")
        await prove_task_routed_to_queue(
            redis_conn=redis_conn,
            expected_queue=BATCH_QUEUE,
            sender=batch_task,
            sender_kwargs={"batch_id": "B-2026-001", "count": 500},
        )
        print()

        print("结论:")
        print("  1. ListQueueBroker 也支持 producer 侧动态 queue_name 路由")
        print("  2. 这里的证明来自 LLEN 增量和 BRPOP 后反序列化结果，不是口头推断")
        print("  3. result backend 可以照常挂在 broker 上，但不改变 List 的消费模型")
        print("  4. ListQueueBroker 仍然只有单 queue_name 监听能力，没有 Stream 的 additional_streams")
        print("  5. 所以 List 的动态路由更适合做 producer 侧分流，而不是直接等价于 Stream 的多队列消费模型")
    finally:
        await redis_conn.aclose()
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
