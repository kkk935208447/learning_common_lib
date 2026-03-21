"""Mock infrastructure implementations for the deep-search demo."""

try:
    from .mock_llm import MockLLM
except ImportError:
    from 最小可执行demo.infrastructure.mock.mock_llm import MockLLM

__all__ = ["MockLLM"]
