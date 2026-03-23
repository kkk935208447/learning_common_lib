"""
Redis Stream 基础拆解 — 从 XADD 到 XACK。

目标:
    不经过 TaskIQ，直接用 redis.asyncio 把 Redis Stream 的关键状态看明白：
      1. XADD 写入消息
      2. XGROUP CREATE 创建消费组
      3. XREADGROUP 读取消息
      4. XPENDING 查看待确认消息
      5. XACK 确认消息

关键概念:
    - Stream 是“可追加日志”，消息不会像 List 一样在消费时直接消失
    - Consumer Group 负责追踪“谁读了、谁 ack 了、谁还没 ack”
    - ACK 不是可选点缀，而是 Stream 可靠消费模型的核心

运行方式:
    python examples/08_redis_stream_broker/01_stream_data_structure_basics.py

预期现象:
    - 你能看到消息写入 stream 后 `XLEN` 增长
    - `XREADGROUP` 后消息进入 pending
    - `XACK` 后 pending 清空
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

REDIS_URL = "redis://default:123456@localhost:6379/0"
STREAM_NAME = "taskiq:examples:08_redis_stream_broker:01:orders"
GROUP_NAME = "taskiq:examples:08_redis_stream_broker:01"
CONSUMER_NAME = "consumer-a"


async def reset_stream(redis_conn: Redis) -> None:
    await redis_conn.delete(STREAM_NAME)


async def print_pending(redis_conn: Redis, title: str) -> None:
    summary = await redis_conn.xpending(STREAM_NAME, GROUP_NAME)
    print(f"{title}: {summary}")


async def main() -> None:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        await reset_stream(redis_conn)

        print("=" * 72)
        print("Redis Stream 基础拆解")
        print("=" * 72)
        print(f"stream   = {STREAM_NAME}")
        print(f"group    = {GROUP_NAME}")
        print(f"consumer = {CONSUMER_NAME}")
        print()

        print("步骤 1: XADD 写入两条消息")
        msg1 = await redis_conn.xadd(STREAM_NAME, {"data": b"order-1001"})
        msg2 = await redis_conn.xadd(STREAM_NAME, {"data": b"order-1002"})
        print(f"  msg1 id = {msg1}")
        print(f"  msg2 id = {msg2}")
        print(f"  XLEN    = {await redis_conn.xlen(STREAM_NAME)}")
        print()

        print("步骤 2: 创建 Consumer Group")
        await redis_conn.xgroup_create(
            STREAM_NAME,
            GROUP_NAME,
            id="0-0",
            mkstream=True,
        )
        print(f"  groups = {await redis_conn.xinfo_groups(STREAM_NAME)}")
        print()

        print("步骤 3: consumer-a 读取一条消息（XREADGROUP）")
        fetched = await redis_conn.xreadgroup(
            GROUP_NAME,
            CONSUMER_NAME,
            {STREAM_NAME: ">"},
            count=1,
            block=100,
        )
        print(f"  fetched = {fetched}")
        await print_pending(redis_conn, "  pending summary")
        print()

        print("步骤 4: 查看 pending 详情")
        pending_detail = await redis_conn.xpending_range(
            STREAM_NAME,
            GROUP_NAME,
            "-",
            "+",
            10,
        )
        print(f"  pending detail = {pending_detail}")
        print()

        print("步骤 5: ACK 刚才那条消息")
        first_id = fetched[0][1][0][0]
        acked = await redis_conn.xack(STREAM_NAME, GROUP_NAME, first_id)
        print(f"  xack count = {acked}")
        await print_pending(redis_conn, "  pending summary after ack")
        print()

        print("结论:")
        print("  1. Stream 消费后消息不会立刻消失，而是进入 pending")
        print("  2. Consumer Group 负责追踪消息是否已确认")
        print("  3. 这就是 RedisStreamBroker 能做 ACK / reclaim 的根基")
    finally:
        await redis_conn.aclose()


if __name__ == "__main__":
    asyncio.run(main())
