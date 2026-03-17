"""Shared Celery app instance and runtime configuration."""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

try:
    from .config import get_settings
    from .enums import QueueName, TaskName
except ImportError:
    from config import get_settings
    from enums import QueueName, TaskName


# Celery app 运行时配置统一收口在这里，CLI 入口和代码调用都复用同一实例。
settings = get_settings()

celery_app = Celery(
    "agentic_rag_min_demo",
    broker=settings.redis_broker_url,
    backend=settings.redis_backend_url,
)

celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_default_queue=QueueName.PARSE.value,
    # demo 规模不大，直接把路由放在 Celery app 配置里比再跳一层模块更直观。
    task_routes={
        TaskName.PARSE_VERSION.value: {"queue": QueueName.PARSE.value},
        TaskName.INDEX_VERSION.value: {"queue": QueueName.INDEX.value},
        TaskName.CLEAN_VERSION.value: {"queue": QueueName.CLEAN.value},
        TaskName.DISPATCH_OUTBOX.value: {"queue": QueueName.REPAIR.value},
        TaskName.JANITOR_SCAN.value: {"queue": QueueName.REPAIR.value},
        TaskName.CLEAN_OUTBOX.value: {"queue": QueueName.HOUSEKEEPING.value},
    },
    # Beat 周期任务也放在这里，阅读 celery 配置时可以一次把入口都看全。
    beat_schedule={
        "dispatch-outbox-every-5-seconds": {
            "task": TaskName.DISPATCH_OUTBOX.value,
            "schedule": schedule(run_every=settings.outbox_dispatch_scan_seconds),
        },
        "janitor-scan": {
            "task": TaskName.JANITOR_SCAN.value,
            "schedule": schedule(run_every=settings.janitor_schedule_seconds),
        },
        "clean-sent-outbox-daily": {
            "task": TaskName.CLEAN_OUTBOX.value,
            # 历史清理任务不追求准点，固定 24 小时轮询已经足够。
            "schedule": schedule(run_every=24 * 60 * 60),
        },
    },
)
