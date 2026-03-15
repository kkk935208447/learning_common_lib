"""
TaskIQ 定时任务 — RedisScheduleSource 动态调度管理。

目标:
    演示如何用 RedisScheduleSource 动态新增、查询、删除调度

关键概念:
    - RedisScheduleSource 将调度信息持久化到 Redis
    - schedule_by_cron / schedule_by_interval / schedule_by_time 是当前版本更直观的动态调度入口
    - Scheduler 和 Worker 是独立进程，本脚本只负责管理调度元数据

关键 API:
    - RedisScheduleSource              — 基于 Redis 的调度源
    - task.schedule_by_cron(...)       — 动态创建 cron 调度
    - task.schedule_by_interval(...)   — 动态创建间隔调度
    - task.schedule_by_time(...)       — 动态创建单次调度
    - CreatedSchedule.unschedule()     — 删除当前调度
    - source.get_schedules()           — 查询所有调度

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
    - Client 动态把调度信息写入 Redis
    - get_schedules() 能看到刚创建的调度
    - 删除调度后，再查询会少一条记录

生产提醒:
    - 生产环境建议只运行一个 scheduler 实例，避免重复触发
    - 动态调度管理不要求客户端先 startup broker；真正消费调度任务的是 scheduler + worker
    - Redis 中保存的是 ScheduledTask 元数据，不是任务执行结果

技术要点:
    - RedisScheduleSource.add_schedule() 当前直接接收 ScheduledTask 对象
    - 更推荐通过 task.schedule_by_* API 创建 ScheduledTask，避免手工拼装
    - 对比 Celery Beat：TaskIQ 支持运行时动态增删调度，无需重启进程
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from taskiq import TaskiqScheduler
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource

BROKER_URL = "redis://default:123456@localhost:6379/0"
RESULT_BACKEND_URL = "redis://default:123456@localhost:6379/1"
QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:07_scheduling:01_redis_schedule_source",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url=RESULT_BACKEND_URL,
    result_ex_time=3600,
)
broker = ListQueueBroker(
    url=BROKER_URL,
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)

# ── 2. 创建 Redis 调度源与 Scheduler ──
schedule_source = RedisScheduleSource(url=BROKER_URL)
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[schedule_source],
)


# ── 3. 定义可被调度的任务 ──


@broker.task(task_name="examples.07_scheduling.01_redis_schedule_source.heartbeat")
async def heartbeat() -> str:
    """心跳任务。"""
    return "alive"


@broker.task(task_name="examples.07_scheduling.01_redis_schedule_source.cleanup_expired")
async def cleanup_expired(table: str, days: int = 30) -> dict:
    """清理过期数据。"""
    return {"table": table, "days": days, "status": "cleaned"}


@broker.task(task_name="examples.07_scheduling.01_redis_schedule_source.generate_report")
async def generate_report(report_type: str) -> dict:
    """生成报表。"""
    return {"report_type": report_type, "status": "generated"}


# ── 4. 客户端：动态管理调度 ──


async def main() -> None:
    """演示：通过 schedule_by_* API 动态添加/查询/删除调度。"""
    print("🚀 演示 RedisScheduleSource 动态调度管理")
    print("=" * 60)

    report_run_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    print("\n📌 添加调度 1 — 心跳任务（每 60 秒）")
    heartbeat_schedule = await heartbeat.schedule_by_interval(
        schedule_source,
        interval=timedelta(seconds=60),
    )
    print(f"   schedule_id = {heartbeat_schedule.schedule_id}")
    print(f"   detail      = {heartbeat_schedule}")

    print("\n📌 添加调度 2 — 清理任务（每天凌晨 2 点）")
    cleanup_schedule = await cleanup_expired.schedule_by_cron(
        schedule_source,
        "0 2 * * *",
        "user_sessions",
        days=7,
    )
    print(f"   schedule_id = {cleanup_schedule.schedule_id}")
    print(f"   detail      = {cleanup_schedule}")

    print("\n📌 添加调度 3 — 报表任务（30 分钟后执行一次）")
    report_schedule = await generate_report.schedule_by_time(
        schedule_source,
        report_run_at,
        "weekly_summary",
    )
    print(f"   schedule_id = {report_schedule.schedule_id}")
    print(f"   detail      = {report_schedule}")

    print("\n📋 查询所有调度:")
    schedules = await schedule_source.get_schedules()
    for i, schedule in enumerate(schedules, 1):
        print(
            f"   {i}. schedule_id={schedule.schedule_id} "
            f"task_name={schedule.task_name} "
            f"cron={schedule.cron} interval={schedule.interval} time={schedule.time}"
        )

    print(f"\n🗑️ 删除调度: schedule_id={heartbeat_schedule.schedule_id}")
    await heartbeat_schedule.unschedule()

    print("\n📋 删除后查询:")
    schedules = await schedule_source.get_schedules()
    for i, schedule in enumerate(schedules, 1):
        print(
            f"   {i}. schedule_id={schedule.schedule_id} "
            f"task_name={schedule.task_name} "
            f"cron={schedule.cron} interval={schedule.interval} time={schedule.time}"
        )

    print()
    print("💡 关键点:")
    print("   - RedisScheduleSource 将调度持久化到 Redis，重启不丢失")
    print("   - task.schedule_by_* 会帮你构造 ScheduledTask，避免手工拼对象")
    print("   - scheduler 负责到点触发，worker 负责实际执行")
    print(f"   - 当前 worker/scheduler 共享的 queue_name = {broker.queue_name!r}")
    print("   - 对比 Celery Beat: TaskIQ 支持动态增删调度，无需重启")


if __name__ == "__main__":
    asyncio.run(main())
