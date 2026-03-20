"""Compatibility wrapper around the current LLM port."""

from __future__ import annotations

try:
    from .llm_port import LLMPort as BaseLLMPort, LLMResponse
except ImportError:
    from 最小可执行demo.ports.llm_port import LLMPort as BaseLLMPort, LLMResponse

__all__ = ["BaseLLMPort", "LLMResponse"]
