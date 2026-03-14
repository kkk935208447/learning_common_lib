"""
TaskIQ 定时任务 — RedisScheduleSource 调度源配置与管理。

目标:
    演示 TaskIQ 定时任务的 Redis 调度源配置

关键概念:
    - RedisScheduleSource 将调度信息存储在 Redis 中
    - 调度器独立进程：taskiq scheduler 命令启动
    - 动态添加/删除/查询调度

关键 API:
    - RedisScheduleSource          — 基于 Redis 的调度源，持久化调度信息
    - source.add_schedule()        — 动态添加调度任务
    - source.get_schedules()       — 查询当前所有调度任务
    - source.delete_schedule()     — 删除指定调度任务
    - TaskiqScheduler              — 调度器，驱动调度源按时触发任务

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/07_scheduling

运行方式:
    Scheduler:
        taskiq scheduler examples.07_scheduling.01_redis_schedule_source:scheduler
    Worker:
        taskiq worker examples.07_scheduling.01_redis_schedule_source:broker
    Client:
        python examples/07_scheduling/01_redis_schedule_source.py

预期现象:
    - Client 动态添加调度任务到 Redis
    - Scheduler 进程按调度配置定时触发任务
    - Worker 进程执行被触发的任务

生产提醒:
    - Scheduler 和 Worker 是独立进程，需分别启动
    - RedisScheduleSource 的调度信息持久化在 Redis 中，重启不丢失
    - 生产环境建议只运行一个 Scheduler 实例，避免重复触发

技术要点:
    - 调度器和 worker 是独立进程
    - RedisScheduleSource 支持持久化调度
    - 对比 Celery Beat：TaskIQ 调度更灵活，支持动态增删
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from taskiq import TaskiqScheduler
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from taskiq_redis import RedisScheduleSource

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
).with_result_backend(result_backend)

# ── 2. 创建 Redis 调度源 ──
# RedisScheduleSource 将调度信息存储在 Redis 中，支持持久化和动态管理
schedule_source = RedisScheduleSource(
    url="redis://default:123456@localhost:6379/0",
)

# ── 3. 创建调度器 ──
# TaskiqScheduler 驱动调度源，按时触发任务发送到 Broker
# 需要通过 `taskiq scheduler` 命令在独立进程中运行
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[schedule_source],
)


# ── 4. 定义任务 ──


@broker.task
async def heartbeat() -> str:
    """心跳任务 — 定时执行，用于健康检查。"""
    import datetime

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"💓 [heartbeat] 心跳检测: {now}")
    return f"alive at {now}"


@broker.task
async def cleanup_expired(table: str, days: int = 30) -> dict:
    """清理过期数据 — 定时清理指定表中的过期记录。"""
    print(f"🧹 [cleanup] 清理 {table} 表中 {days} 天前的数据")
    return {"table": table, "days": days, "status": "cleaned"}


@broker.task
async def generate_report(report_type: str) -> dict:
    """生成报表 — 定时生成业务报表。"""
    print(f"📊 [report] 生成报表: {report_type}")
    return {"report_type": report_type, "status": "generated"}


# ── 5. 客户端：动态管理调度 ──


async def main() -> None:
    """演示：通过 RedisScheduleSource API 动态添加/查询/删除调度。"""
    await broker.startup()

    print("🚀 演示 RedisScheduleSource 动态调度管理")
    print("=" * 60)

    # 添加调度 1: 每 60 秒执行心跳
    print("\n📌 添加调度 1 — 心跳任务（每 60 秒）")
    schedule_id_1 = await schedule_source.add_schedule(
        task=heartbeat,
        # 使用 cron 表达式: 每分钟执行
        cron="* * * * *",
        # 也可以用 cron_offset 指定时区偏移
    )
    print(f"   schedule_id = {schedule_id_1}")

    # 添加调度 2: 每天凌晨 2 点清理过期数据
    print("\n📌 添加调度 2 — 清理任务（每天凌晨 2 点）")
    schedule_id_2 = await schedule_source.add_schedule(
        task=cleanup_expired,
        cron="0 2 * * *",
        args=["user_sessions"],
        kwargs={"days": 7},
    )
    print(f"   schedule_id = {schedule_id_2}")

    # 添加调度 3: 每周一上午 9 点生成周报
    print("\n📌 添加调度 3 — 报表任务（每周一 9:00）")
    schedule_id_3 = await schedule_source.add_schedule(
        task=generate_report,
        cron="0 9 * * 1",
        args=["weekly_summary"],
    )
    print(f"   schedule_id = {schedule_id_3}")

    # 查询所有调度
    print("\n📋 查询所有调度:")
    schedules = await schedule_source.get_schedules()
    for i, sched in enumerate(schedules, 1):
        print(f"   {i}. {sched}")

    # 删除调度 1（心跳任务）
    print(f"\n🗑️ 删除调度: schedule_id={schedule_id_1}")
    await schedule_source.delete_schedule(schedule_id_1)

    # 再次查询，确认删除
    print("\n📋 删除后查询:")
    schedules = await schedule_source.get_schedules()
    for i, sched in enumerate(schedules, 1):
        print(f"   {i}. {sched}")

    print()
    print("💡 关键点:")
    print("   - RedisScheduleSource 将调度持久化到 Redis，重启不丢失")
    print("   - 调度器（scheduler）和 Worker 是独立进程，需分别启动")
    print("   - add_schedule() 支持 cron 表达式和 args/kwargs 参数")
    print("   - 对比 Celery Beat: TaskIQ 支持动态增删调度，无需重启")
    print("   - Celery Beat 的 beat_schedule 是静态配置，修改需重启进程")

    await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
