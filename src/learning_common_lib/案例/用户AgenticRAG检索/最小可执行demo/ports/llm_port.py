"""LLM port for deterministic demo planning and answer generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class LLMResponse(TypedDict, total=False):
    text: str
    structured_output: dict[str, Any] | list[Any] | None
    usage: dict[str, int]
    model: str


class LLMPort(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        structured_schema: Any | None = None,
        timeout_s: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
