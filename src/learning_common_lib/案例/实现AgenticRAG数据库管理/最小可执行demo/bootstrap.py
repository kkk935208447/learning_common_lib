"""Factory helpers that assemble demo adapters without a DI framework."""

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


# 这个模块就是 demo 的“手写组装根”，负责把具体适配器实例化出来。
def build_object_storage() -> FileObjectStorage:
    # demo 保持“显式 new 对象”的简单工厂，不引入更重的依赖注入框架。
    return FileObjectStorage()


def build_vector_store() -> FileVectorStore:
    return FileVectorStore()


def build_search_store() -> FileSearchStore:
    return FileSearchStore()


def build_embedding_provider() -> DeterministicEmbeddingProvider:
    # embedding provider 也通过工厂暴露，后续替换真实模型时不需要改调用方。
    return DeterministicEmbeddingProvider()


def build_lock_port() -> RedisDistributedLock:
    # 锁客户端也从这里集中创建，调用方不用关心 Redis 连接细节。
    return RedisDistributedLock()


def build_task_queue() -> CeleryTaskQueueAdapter:
    # 正常运行路径始终走 Celery；只有 eager/测试才会显式切到内存队列。
    return CeleryTaskQueueAdapter()


def build_in_memory_task_queue() -> InMemoryTaskQueueAdapter:
    # 这个工厂主要给 demo_flow 之类的单进程场景准备。
    return InMemoryTaskQueueAdapter()
