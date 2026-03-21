"""Thin task-queue adapters for the deep-search demo."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

try:
    from ..ports.task_queue_port import TaskDispatchError, TaskQueuePort
except ImportError:
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError, TaskQueuePort


class CeleryTaskQueueAdapter(TaskQueuePort):
    def dispatch(
        self,
        task_name: str,
        payload: dict[str, Any],
        queue_name: str,
        countdown: int | None = None,
    ) -> str | None:
        try:
            from ..workers.celery_app import celery_app
        except ImportError:
            from 最小可执行demo.workers.celery_app import celery_app
        try:
            result = celery_app.send_task(task_name, kwargs=payload, queue=queue_name, countdown=countdown)
        except Exception as exc:
            raise TaskDispatchError(f"任务投递失败: {task_name}") from exc
        return result.id

    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        return [
            self.dispatch(
                task_name=event["task_name"],
                payload=event["payload"],
                queue_name=event["queue_name"],
                countdown=event.get("countdown"),
            )
            for event in events
        ]


class InMemoryTaskQueueAdapter(TaskQueuePort):
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def _dispatch_local(self, task_name: str, payload: dict[str, Any]):
        try:
            from ..workers.maintenance_tasks import (
                apply_clarify_defaults_async,
                reap_stuck_runs_async,
                recover_orchestration_gaps_async,
                rebuild_runtime_cache_async,
            )
            from ..workers.orchestrate_tasks import resume_search_async, start_search_async
            from ..workers.persist_tasks import flush_data_plane_async
            from ..workers.subtask_tasks import execute_subtask_async
        except ImportError:
            from 最小可执行demo.workers.maintenance_tasks import (
                apply_clarify_defaults_async,
                reap_stuck_runs_async,
                recover_orchestration_gaps_async,
                rebuild_runtime_cache_async,
            )
            from 最小可执行demo.workers.orchestrate_tasks import resume_search_async, start_search_async
            from 最小可执行demo.workers.persist_tasks import flush_data_plane_async
            from 最小可执行demo.workers.subtask_tasks import execute_subtask_async

        task_map = {
            "deepsearch.start_search": lambda: start_search_async(**payload),
            "deepsearch.resume_search": lambda: resume_search_async(**payload),
            "deepsearch.execute_subtask": lambda: execute_subtask_async(**payload),
            "deepsearch.flush_data_plane": lambda: flush_data_plane_async(**payload),
            "deepsearch.reap_stuck_runs": lambda: reap_stuck_runs_async(),
            "deepsearch.apply_clarify_defaults": lambda: apply_clarify_defaults_async(),
            "deepsearch.rebuild_runtime_cache": lambda: rebuild_runtime_cache_async(),
            "deepsearch.recover_orchestration_gaps": lambda: recover_orchestration_gaps_async(),
        }
        factory = task_map.get(task_name)
        if factory is None:
            raise ValueError(f"未知本地任务: {task_name}")
        coro = factory()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result_box: dict[str, Any] = {}
        error_box: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result_box["value"] = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - propagated to caller
                error_box["value"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if "value" in error_box:
            raise error_box["value"]
        return result_box.get("value")

    def dispatch(
        self,
        task_name: str,
        payload: dict[str, Any],
        queue_name: str,
        countdown: int | None = None,
    ) -> str | None:
        self.events.append(
            {
                "task_name": task_name,
                "payload": payload,
                "queue_name": queue_name,
                "countdown": countdown,
            }
        )
        self._dispatch_local(task_name, payload)
        return None

    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        return [
            self.dispatch(
                task_name=event["task_name"],
                payload=event["payload"],
                queue_name=event["queue_name"],
                countdown=event.get("countdown"),
            )
            for event in events
        ]
