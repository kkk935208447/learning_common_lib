"""CLI-facing Celery app entry used by `celery -A celery_app:celery_app ...`."""

from __future__ import annotations

try:
    from .celery_runtime import celery_app
    from .task_registry import autodiscover_demo_tasks
except ImportError:
    from celery_runtime import celery_app
    from task_registry import autodiscover_demo_tasks


# 标准 Celery CLI 会 import 这个模块，因此这里直接触发一次任务发现。
# 这样 `uv run celery -A celery_app:celery_app worker ...` 不需要额外手工 import tasks。
autodiscover_demo_tasks(celery_app)
