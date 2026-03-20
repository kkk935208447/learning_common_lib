"""Checkpoint port for LangGraph runtime integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CheckpointPort(ABC):
    @abstractmethod
    async def get_checkpointer(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError
