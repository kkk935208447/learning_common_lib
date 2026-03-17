"""CLI-facing Celery app entry used by `celery -A celery_app:celery_app ...`."""

from __future__ import annotations

try:
    from .celery_runtime import celery_app
    from .task_registry import autodiscover_demo_tasks
except ImportError:
    from celery_runtime import celery_app
    from task_registry import autodiscover_demo_tasks


# 这个文件存在的意义是给 Celery CLI 一个稳定、零参数的导入入口。
# 标准 Celery CLI 会 import 这个模块，因此这里直接触发一次任务发现。
# 这样 `uv run celery -A celery_app:celery_app worker ...` 不需要额外手工 import tasks。
# 也因此这里故意不放其他副作用逻辑，避免 CLI 导入时行为不透明。
autodiscover_demo_tasks(celery_app)
