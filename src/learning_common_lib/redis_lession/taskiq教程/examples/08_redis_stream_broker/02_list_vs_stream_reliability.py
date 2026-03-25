"""
Redis List vs Stream 可靠性对比 — BRPOP 弹走即失 vs pending + reclaim。

目标:
    直接用 Redis 命令拆解 List 和 Stream 的核心差异：
      1. List: `LPUSH/BRPOP`，消息一旦被弹出，broker 侧不再追踪
      2. Stream: `XADD/XREADGROUP/XACK/XAUTOCLAIM`，未 ACK 消息可恢复

关键概念:
    - ListQueueBroker 的优点是简单，缺点是没有 ACK
    - RedisStreamBroker 的核心价值不是“API 新”，而是“消费状态可追踪”
    - 你真正获得的是 pending backlog 和 reclaim 能力

运行方式:
    python examples/08_redis_stream_broker/02_list_vs_stream_reliability.py

预期现象:
    - List 模式下，BRPOP 后队列长度立刻变成 0
    - Stream 模式下，XREADGROUP 后消息进入 pending，而不是直接消失
    - 超过 idle timeout 后，另一个 consumer 可以通过 XAUTOCLAIM 接手
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

REDIS_URL = "redis://default:123456@localhost:6379/0"
LIST_KEY = "taskiq:examples:08_redis_stream_broker:02:list"
STREAM_KEY = "taskiq:examples:08_redis_stream_broker:02:stream"
GROUP_NAME = "taskiq:examples:08_redis_stream_broker:02"


async def compare_list(redis_conn: Redis) -> None:
    print("=" * 72)
    print("Part A: ListQueueBroker 背后的 List 行为")
    print("=" * 72)
    await redis_conn.delete(LIST_KEY)  # 清理 list 中的消息
    await redis_conn.lpush(LIST_KEY, b"job:list:1001")  # 写入消息
    print(f"步骤 1: LPUSH 后 LLEN = {await redis_conn.llen(LIST_KEY)}")

    popped = await redis_conn.brpop([LIST_KEY], timeout=1)
    print(f"步骤 2: BRPOP 取出消息 = {popped}")
    print(f"步骤 3: BRPOP 之后 LLEN = {await redis_conn.llen(LIST_KEY)}")
    print("结论: broker 侧已经不知道这条消息之后会不会真正被业务成功处理。")
    print()


async def compare_stream(redis_conn: Redis) -> None:
    print("=" * 72)
    print("Part B: RedisStreamBroker 背后的 Stream 行为")
    print("=" * 72)
    await redis_conn.delete(STREAM_KEY)   # 清理 stream 中的消息
    await redis_conn.xgroup_create(STREAM_KEY, GROUP_NAME, id="0-0", mkstream=True)  # 创建消费组

    msg_id = await redis_conn.xadd(STREAM_KEY, {"data": b"job:stream:2001"})  # 写入消息
    print(f"步骤 1: XADD 写入消息 id = {msg_id}")
    print(f"        XLEN = {await redis_conn.xlen(STREAM_KEY)}")

    fetched = await redis_conn.xreadgroup(
        GROUP_NAME,
        "consumer-a",       # 表示 consumer-a 读取消息的消费者组名称
        {STREAM_KEY: ">"},  # ">" 表示读取 stream 中尚未被消费的消息
        count=1,  # 读取消息的数量
        block=100,
    )
    print(f"步骤 2: consumer-a XREADGROUP 读取 = {fetched}")
    print(f"        XPENDING summary = {await redis_conn.xpending(STREAM_KEY, GROUP_NAME)}")

    print("步骤 3: 模拟 consumer-a 拿到消息后没有 ACK，等待它变成 idle")
    await asyncio.sleep(1.2)

    claimed = await redis_conn.xautoclaim(
        STREAM_KEY,
        GROUP_NAME,
        "consumer-b",         # 表示 consumer-b 读取消息的消费者组名称
        min_idle_time=1000,   # 表示消息在 stream 中闲置的最小时间
        start_id="0-0",   # 表示从最早的消息开始
        count=10, 
    )
    print(f"步骤 4: consumer-b XAUTOCLAIM 结果 = {claimed}")

    pending_after_claim = await redis_conn.xpending_range(
        STREAM_KEY,
        GROUP_NAME,
        "-",  # 表示从最早的消息开始
        "+",  # 表示到最新的消息结束
        10,   # 表示读取 10 条消息
    )
    print(f"        pending detail after claim = {pending_after_claim}")

    if claimed[1]:
        claimed_id = claimed[1][0][0]   # 表示第一条消息的 ID，claimed 是一个列表，列表中包含一个元组，元组中包含一个列表，列表中包含一个元组，元组中包含一个消息 ID
        acked = await redis_conn.xack(STREAM_KEY, GROUP_NAME, claimed_id)     # 确认消息
        print(f"步骤 5: consumer-b ACK reclaimed 消息，xack count = {acked}")
    print(f"        XPENDING summary after ack = {await redis_conn.xpending(STREAM_KEY, GROUP_NAME)}")
    print()


async def main() -> None:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        await compare_list(redis_conn)
        await compare_stream(redis_conn)

        print("最终结论:")
        print("  1. List 的优势是简单，但 broker 不跟踪消息处理状态")
        print("  2. Stream 通过 pending + ack + autoclaim 提供恢复能力")
        print("  3. 所以 List 适合教学和低门槛接入，Stream 更值得用于生产可靠队列")
    finally:
        await redis_conn.aclose()


if __name__ == "__main__":
    asyncio.run(main())
