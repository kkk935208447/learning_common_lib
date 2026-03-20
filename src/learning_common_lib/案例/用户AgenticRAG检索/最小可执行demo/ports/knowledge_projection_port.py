"""Port for reading active knowledge projections produced by the upstream module."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class ActiveDocumentRef(TypedDict, total=False):
    document_id: int
    external_doc_key: str
    title: str
    active_version_id: int
    storage_key: str


class ActiveScope(TypedDict, total=False):
    kb_code: str
    active_version_ids: list[int]
    documents: list[ActiveDocumentRef]


class ParentDocument(TypedDict, total=False):
    document_id: int | None
    version_id: int
    storage_key: str
    content: str
    metadata: dict[str, Any]


class KnowledgeProjectionReadPort(ABC):
    @abstractmethod
    async def resolve_active_scope(
        self,
        kb_code: str,
        scope_json: dict[str, Any] | None = None,
    ) -> ActiveScope:
        raise NotImplementedError

    @abstractmethod
    async def build_retrieval_filters(self, task_id: int) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def load_parent_document(self, locator: dict[str, Any]) -> ParentDocument:
        raise NotImplementedError
