from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

try:
    from .config import get_settings
    from .enums import QueueName, TaskName
except ImportError:
    from config import get_settings
    from enums import QueueName, TaskName


settings = get_settings()

celery_app = Celery(
    "agentic_rag_min_demo",
    broker=settings.redis_broker_url,
    backend=settings.redis_backend_url,
)

celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_default_queue=QueueName.PARSE.value,
    task_routes={
        TaskName.PARSE_VERSION.value: {"queue": QueueName.PARSE.value},
        TaskName.INDEX_VERSION.value: {"queue": QueueName.INDEX.value},
        TaskName.CLEAN_VERSION.value: {"queue": QueueName.CLEAN.value},
        TaskName.DISPATCH_OUTBOX.value: {"queue": QueueName.REPAIR.value},
        TaskName.JANITOR_SCAN.value: {"queue": QueueName.REPAIR.value},
        TaskName.CLEAN_OUTBOX.value: {"queue": QueueName.HOUSEKEEPING.value},
    },
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
            "schedule": schedule(run_every=24 * 60 * 60),
        },
    },
)

# 让标准 Celery CLI 启动时自动注册任务：
# uv run celery -A celery_app:celery_app worker ...
try:
    from . import tasks as _tasks  # noqa: E402,F401
except ImportError:
    import tasks as _tasks  # noqa: E402,F401
