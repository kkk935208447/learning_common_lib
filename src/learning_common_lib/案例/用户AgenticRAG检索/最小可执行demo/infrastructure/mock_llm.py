"""Compatibility export for the current mock LLM."""

from __future__ import annotations

try:
    from .mock.mock_llm import MockLLM
except ImportError:
    from 最小可执行demo.infrastructure.mock.mock_llm import MockLLM


class MockLLMPort(MockLLM):
    pass
