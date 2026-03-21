"""Adapter factory helpers assembled under infrastructure."""

from __future__ import annotations

from typing import Any

try:
    from .celery_adapter import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from .checkpoint_adapter import LangGraphCheckpointAdapter
    from .file_search_reader import FileSearchReader
    from .file_vector_reader import FileVectorReader
    from .mock.mock_llm import MockLLM
    from .object_storage_reader import ObjectStorageReader
    from .projection_read_adapter import KnowledgeProjectionReader
    from .redis_runtime import RedisRuntime
    from .settings import get_settings
except ImportError:
    from 最小可执行demo.infrastructure.celery_adapter import (
        CeleryTaskQueueAdapter,
        InMemoryTaskQueueAdapter,
    )
    from 最小可执行demo.infrastructure.checkpoint_adapter import (
        LangGraphCheckpointAdapter,
    )
    from 最小可执行demo.infrastructure.file_search_reader import FileSearchReader
    from 最小可执行demo.infrastructure.file_vector_reader import FileVectorReader
    from 最小可执行demo.infrastructure.mock.mock_llm import MockLLM
    from 最小可执行demo.infrastructure.object_storage_reader import ObjectStorageReader
    from 最小可执行demo.infrastructure.projection_read_adapter import (
        KnowledgeProjectionReader,
    )
    from 最小可执行demo.infrastructure.redis_runtime import RedisRuntime
    from 最小可执行demo.infrastructure.settings import get_settings


def _build_test_harness() -> Any | None:
    try:
        from ..test.support.scenario_harness import build_scenario_harness, load_active_scenario_id
    except ImportError:
        from 最小可执行demo.test.support.scenario_harness import (
            build_scenario_harness,
            load_active_scenario_id,
        )
    if not load_active_scenario_id():
        return None
    return build_scenario_harness()


def build_llm() -> MockLLM | Any:
    harness = _build_test_harness()
    if harness is not None:
        return harness.build_llm()
    return MockLLM()


def build_knowledge_projection_port() -> KnowledgeProjectionReader:
    return KnowledgeProjectionReader(ObjectStorageReader())


def build_vector_reader() -> FileVectorReader | Any:
    harness = _build_test_harness()
    if harness is not None:
        return harness.build_vector_reader()
    return FileVectorReader()


def build_search_reader() -> FileSearchReader | Any:
    harness = _build_test_harness()
    if harness is not None:
        return harness.build_search_reader()
    return FileSearchReader()


def build_task_queue():
    return InMemoryTaskQueueAdapter() if get_settings().celery_eager else CeleryTaskQueueAdapter()


def build_redis_runtime() -> RedisRuntime:
    return RedisRuntime()


def build_checkpoint_manager() -> LangGraphCheckpointAdapter:
    return LangGraphCheckpointAdapter()
