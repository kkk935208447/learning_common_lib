"""
目标: 演示 Celery Beat 定时任务调度系统 (Periodic Task Scheduling with Beat)
关键概念:
  - Beat 调度器：独立进程负责定时任务调度，将任务按时发送到队列
  - 调度表达式：crontab() 支持类 Unix cron 语法，timedelta() 支持间隔调度
  - 调度持久化：beat_schedule_filename 存储调度状态，防止重启后重复执行
关键 API: beat_schedule, crontab(), timedelta(), celery beat
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/08_periodic_tasks
运行方式:
  Worker: celery -A examples.08_periodic_tasks.01_celery_beat worker -l info
    (启动 worker 执行定时任务)
  Beat: celery -A examples.08_periodic_tasks.01_celery_beat beat -l info
    (启动 beat 调度器，按配置发送定时任务)
  Client: python examples/08_periodic_tasks/01_celery_beat.py
    (查看调度配置，不发送任务)
预期现象:
  - Beat 进程按 crontab/timedelta 配置定时发送任务到队列
  - Worker 进程接收并执行定时任务
  - 调度状态持久化到 celerybeat-schedule 文件
生产提醒:
  - 生产环境 beat 调度器只能运行一个实例，避免重复调度
  - 运行后可删除 celerybeat-schedule* 文件进行清理
技术要点:
  - crontab(minute, hour, day_of_week, day_of_month, month_of_year)
  - Beat 和 Worker 可以在不同机器上运行
  - 调度精度受 beat_max_loop_interval 参数影响
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.08_periodic_tasks.01_celery_beat",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

# ── 2. 定义周期任务 ──
@app.task
def cleanup_expired_sessions() -> str:
    print("  🧹 清理过期会话")
    return "sessions_cleaned"


@app.task
def generate_daily_report(report_type: str = "sales") -> str:
    print(f"  📊 生成日报: {report_type}")
    return f"report_{report_type}_done"


@app.task
def send_weekly_digest(day: str = "Monday") -> str:
    print(f"  📧 发送周报: {day}")
    return "digest_sent"


@app.task
def sync_inventory() -> str:
    print("  📦 同步库存数据")
    return "inventory_synced"


@app.task
def sunrise_task() -> str:
    print("  🌅 日出触发任务")
    return "sunrise_done"


# ── 3. 配置 beat_schedule ──
app.conf.beat_schedule = {
    # timedelta 调度 — 固定间隔
    "cleanup-every-30s": {
        "task": "examples.08_periodic_tasks.01_celery_beat.cleanup_expired_sessions",
        "schedule": timedelta(seconds=30),
    },

    # crontab 调度 — 类 cron 表达式
    # crontab(minute, hour, day_of_week, day_of_month, month_of_year)
    "daily-report-9am": {
        "task": "examples.08_periodic_tasks.01_celery_beat.generate_daily_report",
        "schedule": crontab(minute=0, hour=9),  # 每天 9:00
        "args": ("sales",),
    },
    "weekly-digest-monday": {
        "task": "examples.08_periodic_tasks.01_celery_beat.send_weekly_digest",
        "schedule": crontab(
            minute=0,
            hour=10,
            day_of_week="monday",  # 每周一 10:00
        ),
        "kwargs": {"day": "Monday"},
    },
    "monthly-inventory-1st": {
        "task": "examples.08_periodic_tasks.01_celery_beat.sync_inventory",
        "schedule": crontab(
            minute=0,
            hour=2,
            day_of_month=1,        # 每月 1 号凌晨 2:00
        ),
    },
    "quarterly-audit": {
        "task": "examples.08_periodic_tasks.01_celery_beat.generate_daily_report",
        "schedule": crontab(
            minute=0,
            hour=6,
            day_of_month=1,
            month_of_year="1,4,7,10",  # 每季度第一天 6:00
        ),
        "args": ("quarterly_audit",),
    },

    # solar 调度 — 基于日出日落 (需要 ephem 库和经纬度)
    # "sunrise-task-shanghai": {
    #     "task": "examples.08_periodic_tasks.01_celery_beat.sunrise_task",
    #     "schedule": solar("sunrise", 31.23, 121.47),  # 上海日出时刻
    # },
}

# ── 4. Beat 相关配置 ──
app.conf.update(
    # beat 调度器存储文件 (默认 shelve)
    beat_schedule_filename="celerybeat-schedule",
    # beat 最大循环间隔 (秒)
    beat_max_loop_interval=5.0,
)


# ── 5. 入口 ──
async def main() -> None:
    print("🚀 Celery Beat 定时任务示例\n")

    # 打印调度配置表
    print("── Beat 调度配置表 ──")
    for name, entry in app.conf.beat_schedule.items():
        schedule = entry["schedule"]
        schedule_type = type(schedule).__name__
        args = entry.get("args", ())
        kwargs = entry.get("kwargs", {})
        print(f"\n  📅 {name}")
        print(f"     任务: {entry['task']}")
        print(f"     调度类型: {schedule_type}")
        print(f"     调度规则: {schedule}")
        if args:
            print(f"     args: {args}")
        if kwargs:
            print(f"     kwargs: {kwargs}")
    print()

    # crontab 用法速查
    print("── crontab 速查表 ──")
    examples = [
        ("每分钟执行", "crontab()"),
        ("每小时整点", "crontab(minute=0)"),
        ("每天 9:30", "crontab(minute=30, hour=9)"),
        ("周一到周五 8:00", "crontab(minute=0, hour=8, day_of_week='mon-fri')"),
        ("每月 1,15 号", "crontab(minute=0, hour=0, day_of_month='1,15')"),
        ("每 15 分钟", "crontab(minute='*/15')"),
    ]
    for desc, expr in examples:
        print(f"  💡 {desc:<20} → {expr}")
    print()

    # 手动执行一个任务验证
    print("── 手动触发验证 ──")
    r1 = await asyncio.to_thread(cleanup_expired_sessions.delay)
    print(f"  ✅ cleanup_expired_sessions: {await asyncio.to_thread(r1.get, timeout=30)}")

    r2 = await asyncio.to_thread(generate_daily_report.delay, "sales")
    print(f"  ✅ generate_daily_report: {await asyncio.to_thread(r2.get, timeout=30)}")
    print()

    # 启动命令说明
    print("── 生产环境启动命令 ──")
    print("  💡 celery -A myproj.celery_app:app beat --loglevel=info")
    print("  💡 celery -A myproj.celery_app:app beat -S django_celery_beat.schedulers:DatabaseScheduler")
    print("  💡 celery -A myproj.celery_app:app worker --beat    # worker + beat 合并 (仅开发用)")
    print("  ⚠️  生产环境 beat 只能运行一个实例，否则任务会重复执行!")


if __name__ == "__main__":
    asyncio.run(main())
