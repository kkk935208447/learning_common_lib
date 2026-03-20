"""Task queue port used by API and orchestration services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TaskQueuePort(ABC):
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
