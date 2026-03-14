"""
TaskIQ 定时任务 — cron 表达式与间隔调度的配置方式。

目标:
    演示 cron 表达式和间隔调度的配置方式

关键概念:
    - cron 表达式调度（如 "*/5 * * * *" 每 5 分钟）
    - 间隔调度（如每 30 秒）
    - 对比 Celery Beat 的 crontab/schedule

关键 API:
    - ScheduledTask                — 描述一个调度任务的数据对象
    - TaskiqScheduler              — 调度器，接收调度源列表
    - LabelScheduleSource          — 基于 labels 的调度源（静态配置）

目录导航:
    - 从项目根目录: cd src/learning_common_lib/redis_lession/taskiq教程
    - 从上级目录: cd examples/07_scheduling

运行方式:
    python examples/07_scheduling/02_cron_and_interval.py（演示配置，不需要 worker）

预期现象:
    - 打印各种调度配置的 ScheduledTask 对象
    - 展示 cron 表达式和间隔调度的不同写法

生产提醒:
    - cron 表达式使用标准 5 段格式: 分 时 日 月 周
    - 间隔调度通过 cron 表达式模拟（如 */N * * * *）
    - 生产环境推荐使用 RedisScheduleSource 实现动态调度

技术要点:
    - TaskIQ 使用 ScheduledTask 对象描述调度
    - cron 字段支持标准 5 段 cron 表达式
    - 对比 Celery：无需 beat_schedule 字典，配置更直观
"""

from __future__ import annotations

import asyncio
import os

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

QUEUE_NAME = os.getenv(
    "TASKIQ_QUEUE_NAME",
    "taskiq:examples:07_scheduling:02_cron_and_interval",
)

# ── 1. 创建 Broker + Result Backend ──
result_backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=QUEUE_NAME,
).with_result_backend(result_backend)


# ── 2. 使用 labels 配置 cron 调度 ──
# LabelScheduleSource 从任务的 labels 中读取 cron/schedule 配置
# 这是静态调度方式，调度信息写在代码中


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.every_minute_task",
    schedule=[{"cron": "* * * * *"}],
)
async def every_minute_task() -> str:
    """每分钟执行一次的任务。

    cron 表达式: * * * * *
    含义: 分(每分钟) 时(每小时) 日(每天) 月(每月) 周(每天)
    """
    print("⏰ [每分钟] 任务执行")
    return "every_minute"


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.every_5_minutes_task",
    schedule=[{"cron": "*/5 * * * *"}],
)
async def every_5_minutes_task() -> str:
    """每 5 分钟执行一次的任务。

    cron 表达式: */5 * * * *
    含义: 每 5 分钟执行一次
    """
    print("⏰ [每5分钟] 任务执行")
    return "every_5_minutes"


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.daily_cleanup",
    schedule=[{"cron": "0 2 * * *"}],
)
async def daily_cleanup() -> str:
    """每天凌晨 2 点执行的清理任务。

    cron 表达式: 0 2 * * *
    含义: 每天 02:00 执行
    """
    print("🧹 [每日清理] 凌晨 2 点执行")
    return "daily_cleanup"


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.weekly_report",
    schedule=[{"cron": "0 9 * * 1"}],
)
async def weekly_report() -> str:
    """每周一上午 9 点生成周报。

    cron 表达式: 0 9 * * 1
    含义: 每周一 09:00 执行（1 = Monday）
    """
    print("📊 [周报] 每周一 9 点生成")
    return "weekly_report"


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.monthly_billing",
    schedule=[{"cron": "0 0 1 * *"}],
)
async def monthly_billing() -> str:
    """每月 1 号零点执行的账单任务。

    cron 表达式: 0 0 1 * *
    含义: 每月 1 号 00:00 执行
    """
    print("💰 [月度账单] 每月 1 号执行")
    return "monthly_billing"


# ── 3. 使用 labels 配置带参数的调度 ──


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.cleanup_expired",
    schedule=[
        {
            "cron": "*/10 * * * *",
            "args": ["user_sessions"],
            "kwargs": {"days": 7},
        }
    ]
)
async def cleanup_expired(table: str, days: int = 30) -> dict:
    """每 10 分钟清理过期数据（带参数的调度）。"""
    print(f"🧹 清理 {table} 表中 {days} 天前的数据")
    return {"table": table, "days": days}


# ── 4. 多调度配置（一个任务多个调度） ──


@broker.task(
    task_name="examples.07_scheduling.02_cron_and_interval.twice_daily_sync",
    schedule=[
        {"cron": "0 9 * * *"},   # 每天 9 点
        {"cron": "0 18 * * *"},  # 每天 18 点
    ]
)
async def twice_daily_sync() -> str:
    """每天执行两次的同步任务（9:00 和 18:00）。"""
    print("🔄 [双次同步] 任务执行")
    return "twice_daily"


# ── 5. 创建调度器（使用 LabelScheduleSource） ──
# LabelScheduleSource 从任务的 labels 中读取 schedule 配置
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)


# ── 6. 打印调度配置说明 ──


async def main() -> None:
    """演示：打印各种 cron 调度配置，帮助理解调度语法。"""
    print("📅 TaskIQ 定时任务 — cron 表达式与间隔调度")
    print("=" * 60)

    print("\n🔤 cron 表达式格式（5 段）:")
    print("   ┌───────────── 分钟 (0-59)")
    print("   │ ┌─────────── 小时 (0-23)")
    print("   │ │ ┌───────── 日   (1-31)")
    print("   │ │ │ ┌─────── 月   (1-12)")
    print("   │ │ │ │ ┌───── 星期 (0-7, 0和7都是周日)")
    print("   │ │ │ │ │")
    print("   * * * * *")

    print("\n📋 本文件中的调度配置:")
    schedules = [
        ("every_minute_task",   "* * * * *",     "每分钟执行"),
        ("every_5_minutes_task", "*/5 * * * *",  "每 5 分钟执行"),
        ("daily_cleanup",       "0 2 * * *",     "每天凌晨 2 点"),
        ("weekly_report",       "0 9 * * 1",     "每周一 9:00"),
        ("monthly_billing",     "0 0 1 * *",     "每月 1 号 0:00"),
        ("cleanup_expired",     "*/10 * * * *",  "每 10 分钟（带参数）"),
        ("twice_daily_sync",    "0 9,18 * * *",  "每天 9:00 和 18:00"),
    ]
    for name, cron, desc in schedules:
        print(f"   {name:<25s} {cron:<15s} → {desc}")

    print("\n🔧 常用 cron 表达式速查:")
    cron_examples = [
        ("*/N * * * *",   "每 N 分钟（间隔调度）"),
        ("0 */N * * *",   "每 N 小时"),
        ("0 0 * * *",     "每天零点"),
        ("0 0 * * 0",     "每周日零点"),
        ("0 0 1,15 * *",  "每月 1 号和 15 号"),
        ("30 4 * * 1-5",  "工作日 4:30"),
    ]
    for cron, desc in cron_examples:
        print(f"   {cron:<15s} → {desc}")

    print("\n💡 关键点:")
    print("   - LabelScheduleSource: 从 @broker.task(schedule=[...]) 读取调度")
    print("   - RedisScheduleSource: 动态管理调度（见 01_redis_schedule_source.py）")
    print("   - schedule 参数是列表，一个任务可配置多个调度")
    print(f"   - 当前调度任务默认发布到 queue_name = {broker.queue_name!r}")
    print("   - 启动调度器: taskiq scheduler module:scheduler")
    print()
    print("📊 对比 Celery Beat:")
    print("   Celery:  app.conf.beat_schedule = {'task-name': {'task': ..., 'schedule': crontab(...)}}")
    print("   TaskIQ:  @broker.task(schedule=[{'cron': '...'}])  ← 更简洁直观")
    print("   Celery Beat 修改调度需重启进程，TaskIQ + RedisScheduleSource 支持动态增删")


if __name__ == "__main__":
    asyncio.run(main())
