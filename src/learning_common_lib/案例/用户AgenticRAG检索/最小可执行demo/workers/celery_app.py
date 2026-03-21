"""Celery application for the deepsearch minimum demo."""

from __future__ import annotations

from celery import Celery

try:
    from ..domain.enums import QueueName, TaskName
    from ..infrastructure.settings import get_settings
    from .maintenance_tasks import (
        apply_clarify_defaults_task,
        reap_stuck_runs_task,
        recover_orchestration_gaps_task,
        rebuild_runtime_cache_task,
    )
    from .orchestrate_tasks import resume_search_task, start_search_task
    from .persist_tasks import flush_data_plane_task
    from .subtask_tasks import execute_subtask_task
except ImportError:
    import sys
    from pathlib import Path

    package_parent = Path(__file__).resolve().parents[2]
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))
    from 最小可执行demo.domain.enums import QueueName, TaskName
    from 最小可执行demo.infrastructure.settings import get_settings
    from 最小可执行demo.workers.maintenance_tasks import (
        apply_clarify_defaults_task,
        reap_stuck_runs_task,
        recover_orchestration_gaps_task,
        rebuild_runtime_cache_task,
    )
    from 最小可执行demo.workers.orchestrate_tasks import (
        resume_search_task,
        start_search_task,
    )
    from 最小可执行demo.workers.persist_tasks import flush_data_plane_task
    from 最小可执行demo.workers.subtask_tasks import execute_subtask_task


settings = get_settings()
celery_app = Celery(
    "deepsearch_demo",
    broker=settings.redis_broker_url,
    backend=settings.redis_backend_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_always_eager=settings.celery_eager,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "deepsearch-reap-stuck-runs": {
            "task": TaskName.REAP_STUCK_RUNS.value,
            "schedule": settings.maintenance_scan_seconds,
        },
        "deepsearch-apply-clarify-defaults": {
            "task": TaskName.APPLY_CLARIFY_DEFAULTS.value,
            "schedule": settings.maintenance_scan_seconds,
        },
        "deepsearch-recover-orchestration-gaps": {
            "task": TaskName.RECOVER_ORCHESTRATION_GAPS.value,
            "schedule": settings.maintenance_scan_seconds,
        },
        "deepsearch-rebuild-runtime-cache": {
            "task": TaskName.REBUILD_RUNTIME_CACHE.value,
            "schedule": max(settings.maintenance_scan_seconds * 3, 30),
        },
    },
    task_routes={
        TaskName.START_SEARCH.value: {"queue": QueueName.ORCHESTRATE.value},
        TaskName.RESUME_SEARCH.value: {"queue": QueueName.ORCHESTRATE.value},
        TaskName.EXECUTE_SUBTASK.value: {"queue": QueueName.SUBTASK.value},
        TaskName.FLUSH_DATA_PLANE.value: {"queue": QueueName.PERSIST.value},
        TaskName.REAP_STUCK_RUNS.value: {"queue": QueueName.MAINTENANCE.value},
        TaskName.APPLY_CLARIFY_DEFAULTS.value: {"queue": QueueName.MAINTENANCE.value},
        TaskName.RECOVER_ORCHESTRATION_GAPS.value: {"queue": QueueName.MAINTENANCE.value},
        TaskName.REBUILD_RUNTIME_CACHE.value: {"queue": QueueName.MAINTENANCE.value},
    },
)

celery_app.task(name=TaskName.START_SEARCH.value, queue=QueueName.ORCHESTRATE.value)(start_search_task)
celery_app.task(name=TaskName.RESUME_SEARCH.value, queue=QueueName.ORCHESTRATE.value)(resume_search_task)
celery_app.task(name=TaskName.EXECUTE_SUBTASK.value, queue=QueueName.SUBTASK.value)(execute_subtask_task)
celery_app.task(name=TaskName.FLUSH_DATA_PLANE.value, queue=QueueName.PERSIST.value)(flush_data_plane_task)
celery_app.task(name=TaskName.REAP_STUCK_RUNS.value, queue=QueueName.MAINTENANCE.value)(reap_stuck_runs_task)
celery_app.task(name=TaskName.APPLY_CLARIFY_DEFAULTS.value, queue=QueueName.MAINTENANCE.value)(apply_clarify_defaults_task)
celery_app.task(name=TaskName.RECOVER_ORCHESTRATION_GAPS.value, queue=QueueName.MAINTENANCE.value)(recover_orchestration_gaps_task)
celery_app.task(name=TaskName.REBUILD_RUNTIME_CACHE.value, queue=QueueName.MAINTENANCE.value)(rebuild_runtime_cache_task)
