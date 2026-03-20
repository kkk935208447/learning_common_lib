"""Compatibility wrapper around the current read-side store ports."""

from __future__ import annotations

try:
    from .knowledge_projection_port import KnowledgeProjectionReadPort as BaseKnowledgeProjectionReadPort
    from .object_storage_port import ObjectStorageReadPort as BaseObjectStorageReadPort
    from .search_read_port import SearchReadPort as BaseSearchReadPort
    from .vector_read_port import VectorReadPort as BaseVectorReadPort
except ImportError:
    from 最小可执行demo.ports.knowledge_projection_port import KnowledgeProjectionReadPort as BaseKnowledgeProjectionReadPort
    from 最小可执行demo.ports.object_storage_port import ObjectStorageReadPort as BaseObjectStorageReadPort
    from 最小可执行demo.ports.search_read_port import SearchReadPort as BaseSearchReadPort
    from 最小可执行demo.ports.vector_read_port import VectorReadPort as BaseVectorReadPort

__all__ = [
    "BaseKnowledgeProjectionReadPort",
    "BaseObjectStorageReadPort",
    "BaseSearchReadPort",
    "BaseVectorReadPort",
]
