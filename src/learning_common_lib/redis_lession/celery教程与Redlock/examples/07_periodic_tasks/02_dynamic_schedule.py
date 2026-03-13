"""
目标: 演示动态调度管理与配置 (Dynamic Schedule Management)
关键 API: app.conf.beat_schedule, add_periodic_task(), DatabaseScheduler
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
运行方式:
  Worker: celery -A examples.07_periodic_tasks.02_dynamic_schedule worker -l info
  Client: python examples/07_periodic_tasks/02_dynamic_schedule.py
预期现象: 展示调度表的增删改过程，演示动态调度概念
生产提醒: 动态调度推荐使用 django-celery-beat 的 DatabaseScheduler 持久化
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.07_periodic_tasks.02_dynamic_schedule",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)

# ── 2. 定义任务 ──
@app.task
def health_check(service: str = "api") -> str:
    print(f"  💓 健康检查: {service}")
    return f"{service}_ok"


@app.task
def sync_data(source: str = "db") -> str:
    print(f"  🔄 数据同步: {source}")
    return f"{source}_synced"


@app.task
def send_report(report_type: str = "daily") -> str:
    print(f"  📊 发送报告: {report_type}")
    return f"{report_type}_sent"


# ── 3. 初始调度表 ──
app.conf.beat_schedule = {
    "health-check-30s": {
        "task": "examples.07_periodic_tasks.02_dynamic_schedule.health_check",
        "schedule": timedelta(seconds=30),
        "args": ("api",),
    },
}


# ── 4. 动态调度管理工具函数 ──
def print_schedule(label: str) -> None:
    """打印当前调度表"""
    print(f"\n  📋 当前调度表 ({label}):")
    if not app.conf.beat_schedule:
        print("     (空)")
        return
    for name, entry in app.conf.beat_schedule.items():
        sched = entry["schedule"]
        print(f"     • {name}: {type(sched).__name__}({sched})")


def add_schedule(name: str, task: str, schedule: timedelta | crontab,
                 args: tuple = (), kwargs: dict | None = None) -> None:
    """添加调度条目
    ⚠️ 直接修改 beat_schedule 字典只在 beat 尚未启动时有效。已运行的 beat 不会感知到内存中的变更。生产环境应使用 DatabaseScheduler (django-celery-beat) 实现真正的动态调度。
    """
    app.conf.beat_schedule[name] = {
        "task": task,
        "schedule": schedule,
        "args": args,
        "kwargs": kwargs or {},
    }
    print(f"  ➕ 已添加: {name}")


def remove_schedule(name: str) -> None:
    """删除调度条目"""
    if name in app.conf.beat_schedule:
        del app.conf.beat_schedule[name]
        print(f"  ➖ 已删除: {name}")
    else:
        print(f"  ⚠️ 未找到: {name}")


def modify_schedule(name: str, **updates: object) -> None:
    """修改调度条目"""
    if name in app.conf.beat_schedule:
        app.conf.beat_schedule[name].update(updates)
        print(f"  ✏️ 已修改: {name} → {updates}")
    else:
        print(f"  ⚠️ 未找到: {name}")


# ── 5. 入口 ──
async def main() -> None:
    print("🚀 Celery 动态调度示例\n")

    # 查看初始调度表
    print("── 步骤 1: 初始调度表 ──")
    print_schedule("初始")

    # 添加新调度
    print("\n── 步骤 2: 添加调度条目 ──")
    add_schedule(
        "sync-data-every-60s",
        "examples.07_periodic_tasks.02_dynamic_schedule.sync_data",
        timedelta(seconds=60),
        args=("mysql",),
    )
    add_schedule(
        "daily-report-9am",
        "examples.07_periodic_tasks.02_dynamic_schedule.send_report",
        crontab(minute=0, hour=9),
        args=("daily",),
    )
    print_schedule("添加后")

    # 修改调度间隔
    print("\n── 步骤 3: 修改调度间隔 ──")
    modify_schedule(
        "health-check-30s",
        schedule=timedelta(seconds=10),  # 30s → 10s
    )
    modify_schedule(
        "sync-data-every-60s",
        args=("postgresql",),  # 修改参数
    )
    print_schedule("修改后")

    # 删除调度
    print("\n── 步骤 4: 删除调度条目 ──")
    remove_schedule("daily-report-9am")
    remove_schedule("nonexistent-task")  # 演示删除不存在的条目
    print_schedule("删除后")

    # 验证任务可执行
    print("\n── 步骤 5: 验证任务执行 ──")
    r1 = await asyncio.to_thread(health_check.delay, "api")
    print(f"  ✅ health_check: {await asyncio.to_thread(r1.get, timeout=30)}")

    r2 = await asyncio.to_thread(sync_data.delay, "postgresql")
    print(f"  ✅ sync_data: {await asyncio.to_thread(r2.get, timeout=30)}")

    # on_after_configure 钩子方式 (推荐)
    print("\n── 补充: on_after_configure 钩子方式 ──")
    print("  💡 使用 @app.on_after_configure.connect 在应用配置完成后添加周期任务:")
    print("     @app.on_after_configure.connect")
    print("     def setup_periodic_tasks(sender, **kwargs):")
    print("         sender.add_periodic_task(10.0, health_check.s('api'))")
    print("         sender.add_periodic_task(")
    print("             crontab(hour=9, minute=0),")
    print("             send_report.s('daily'),")
    print("         )")

    # DatabaseScheduler 说明
    print("\n── 补充: DatabaseScheduler (django-celery-beat) ──")
    print("  💡 安装: pip install django-celery-beat")
    print("  💡 启动: celery -A myproj.celery_app:app beat -S django_celery_beat.schedulers:DatabaseScheduler")
    print("  💡 优势:")
    print("     • 调度配置持久化到数据库，重启不丢失")
    print("     • 可通过 Django Admin 界面管理")
    print("     • 支持 IntervalSchedule / CrontabSchedule / SolarSchedule")
    print("     • 多实例部署时调度表一致")


if __name__ == "__main__":
    asyncio.run(main())
