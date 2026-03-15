from __future__ import annotations

try:
    from .embedding import DeterministicEmbeddingProvider
    from .locks import RedisDistributedLock
    from .search_store import FileSearchStore
    from .storage import FileObjectStorage
    from .task_queue import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from .vector_store import FileVectorStore
except ImportError:
    from embedding import DeterministicEmbeddingProvider
    from locks import RedisDistributedLock
    from search_store import FileSearchStore
    from storage import FileObjectStorage
    from task_queue import CeleryTaskQueueAdapter, InMemoryTaskQueueAdapter
    from vector_store import FileVectorStore


def build_object_storage() -> FileObjectStorage:
    return FileObjectStorage()


def build_vector_store() -> FileVectorStore:
    return FileVectorStore()


def build_search_store() -> FileSearchStore:
    return FileSearchStore()


def build_embedding_provider() -> DeterministicEmbeddingProvider:
    return DeterministicEmbeddingProvider()


def build_lock_port() -> RedisDistributedLock:
    return RedisDistributedLock()


def build_task_queue() -> CeleryTaskQueueAdapter:
    return CeleryTaskQueueAdapter()


def build_in_memory_task_queue() -> InMemoryTaskQueueAdapter:
    return InMemoryTaskQueueAdapter()
