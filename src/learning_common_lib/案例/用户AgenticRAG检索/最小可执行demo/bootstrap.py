"""Factory helpers that assemble the deep-search demo adapters."""

from __future__ import annotations

try:
    from .infrastructure.celery_adapter import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from .infrastructure.checkpoint_adapter import LangGraphCheckpointAdapter
    from .infrastructure.file_search_reader import FileSearchReader
    from .infrastructure.file_vector_reader import FileVectorReader
    from .infrastructure.mock.mock_llm import MockLLM
    from .infrastructure.object_storage_reader import ObjectStorageReader
    from .infrastructure.projection_read_adapter import KnowledgeProjectionReader
    from .infrastructure.redis_runtime import RedisRuntime
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.infrastructure.celery_adapter import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from 最小可执行demo.infrastructure.checkpoint_adapter import LangGraphCheckpointAdapter
    from 最小可执行demo.infrastructure.file_search_reader import FileSearchReader
    from 最小可执行demo.infrastructure.file_vector_reader import FileVectorReader
    from 最小可执行demo.infrastructure.mock.mock_llm import MockLLM
    from 最小可执行demo.infrastructure.object_storage_reader import ObjectStorageReader
    from 最小可执行demo.infrastructure.projection_read_adapter import KnowledgeProjectionReader
    from 最小可执行demo.infrastructure.redis_runtime import RedisRuntime


def build_llm() -> MockLLM:
    return MockLLM()


def build_knowledge_projection_port() -> KnowledgeProjectionReader:
    return KnowledgeProjectionReader(ObjectStorageReader())


def build_vector_reader() -> FileVectorReader:
    return FileVectorReader()

def build_search_reader() -> FileSearchReader:
    return FileSearchReader()

def build_task_queue():
    try:
        from .config import get_settings
    except ImportError:
        import sys
        from pathlib import Path

        demo_parent = Path(__file__).resolve().parent.parent
        if str(demo_parent) not in sys.path:
            sys.path.insert(0, str(demo_parent))
        from 最小可执行demo.config import get_settings
    return InMemoryTaskQueueAdapter() if get_settings().celery_eager else CeleryTaskQueueAdapter()


def build_redis_runtime() -> RedisRuntime:
    return RedisRuntime()


def build_checkpoint_manager() -> LangGraphCheckpointAdapter:
    return LangGraphCheckpointAdapter()
