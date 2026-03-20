"""Factory helpers that assemble the deep-search demo adapters."""

from __future__ import annotations

try:
    from .infrastructure.celery_adapter import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from .infrastructure.checkpoint_adapter import LangGraphCheckpointAdapter
    from .infrastructure.file_search_reader import FileSearchReader
    from .infrastructure.file_vector_reader import FileVectorReader
    from .infrastructure.mock_llm import MockLLMPort
    from .infrastructure.object_storage_reader import ObjectStorageReader
    from .infrastructure.projection_read_adapter import KnowledgeProjectionReader
    from .infrastructure.redis_runtime import RedisDistributedLock, RedisRuntime, RedisSessionStore
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
    from 最小可执行demo.infrastructure.mock_llm import MockLLMPort
    from 最小可执行demo.infrastructure.object_storage_reader import ObjectStorageReader
    from 最小可执行demo.infrastructure.projection_read_adapter import KnowledgeProjectionReader
    from 最小可执行demo.infrastructure.redis_runtime import RedisDistributedLock, RedisRuntime, RedisSessionStore


def build_llm() -> MockLLMPort:
    return MockLLMPort()


def build_llm_port() -> MockLLMPort:
    return build_llm()


def build_knowledge_projection_port() -> KnowledgeProjectionReader:
    return KnowledgeProjectionReader(build_object_storage_port())


def build_vector_reader() -> FileVectorReader:
    return FileVectorReader()


def build_vector_read_port() -> FileVectorReader:
    return build_vector_reader()


def build_search_reader() -> FileSearchReader:
    return FileSearchReader()


def build_search_read_port() -> FileSearchReader:
    return build_search_reader()


def build_object_storage_reader() -> ObjectStorageReader:
    return ObjectStorageReader()


def build_object_storage_port() -> ObjectStorageReader:
    return build_object_storage_reader()


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


def build_local_task_queue():
    return InMemoryTaskQueueAdapter()


def build_in_memory_task_queue():
    return build_local_task_queue()


def build_redis_runtime() -> RedisRuntime:
    return RedisRuntime()


def build_lock_port() -> RedisDistributedLock:
    return RedisDistributedLock()


def build_session_store_port() -> RedisSessionStore:
    return RedisSessionStore()


def build_checkpoint_manager() -> LangGraphCheckpointAdapter:
    return LangGraphCheckpointAdapter()


def build_checkpoint_port() -> LangGraphCheckpointAdapter:
    return build_checkpoint_manager()
