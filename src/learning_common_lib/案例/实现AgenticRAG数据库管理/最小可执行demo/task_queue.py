"""Task queue adapters used by the Outbox dispatcher and eager mode tests."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# 任务队列抽象把“生成异步任务”与“具体由 Celery 还是本地执行”隔开。
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
        try:
            from .celery_app import celery_app
            from .task_registry import autodiscover_demo_tasks
        except ImportError:
            from celery_app import celery_app
            from task_registry import autodiscover_demo_tasks

        # API / Outbox 并不保证提前 import 过 tasks，这里按需 discovery 一次最稳妥。
        autodiscover_demo_tasks(celery_app)
        task = celery_app.tasks[task_name]
        result = task.apply_async(kwargs=payload, queue=queue_name, countdown=countdown)
        return result.id

    def dispatch_batch(self, events: list[dict[str, Any]]) -> list[str | None]:
        # 批量派发本质仍是逐条投递，保持实现简单并复用单条派发逻辑。
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
        # 内存适配器只记录事件快照，方便 eager 模式和测试断言。
        self.events: list[dict[str, Any]] = []

    def dispatch(
        self,
        task_name: str,
        payload: dict[str, Any],
        queue_name: str,
        countdown: int | None = None,
    ) -> str | None:
        # 内存队列只服务测试/演示，不承担真正异步执行。
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
