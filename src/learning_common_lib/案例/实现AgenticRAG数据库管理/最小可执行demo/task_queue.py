from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTaskQueue(ABC):
    @abstractmethod
    def dispatch(
        self,
        task_name: str,
        payload: dict[str, Any],
        queue_name: str,
        countdown: int | None = None,
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        raise NotImplementedError


class CeleryTaskQueueAdapter(BaseTaskQueue):
    def dispatch(
        self,
        task_name: str,
        payload: dict[str, Any],
        queue_name: str,
        countdown: int | None = None,
    ) -> str | None:
        from tasks import ensure_tasks_registered
        from celery_app import celery_app

        ensure_tasks_registered()
        task = celery_app.tasks[task_name]
        result = task.apply_async(kwargs=payload, queue=queue_name, countdown=countdown)
        return result.id

    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        return [
            self.dispatch(
                task_name=event["task_name"],
                payload=event["payload_json"],
                queue_name=event["queue_name"],
                countdown=event.get("countdown"),
            )
            for event in events
        ]


class InMemoryTaskQueueAdapter(BaseTaskQueue):
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

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
        return None

    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        for event in events:
            self.events.append(event)
        return [None for _ in events]
