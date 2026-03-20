"""Adapters that read active knowledge scope from the upstream database management demo."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

try:
    from ....实现AgenticRAG数据库管理.最小可执行demo.models import Document as UpstreamDocument
    from ....实现AgenticRAG数据库管理.最小可执行demo.models import DocumentVersion as UpstreamDocumentVersion
    from ..db import task_session_scope
    from ..domain.enums import SearchTaskStatus
    from ..ports.knowledge_projection_port import ActiveDocumentRef, ActiveScope, KnowledgeProjectionReadPort, ParentDocument
    from ..ports.object_storage_port import ObjectStorageReadPort
    from .repositories import SearchTaskRepository
except ImportError:
    cases_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(cases_root) not in sys.path:
        sys.path.insert(0, str(cases_root))
    from 实现AgenticRAG数据库管理.最小可执行demo.models import (
        Document as UpstreamDocument,
    )
    from 实现AgenticRAG数据库管理.最小可执行demo.models import (
        DocumentVersion as UpstreamDocumentVersion,
    )
    from 最小可执行demo.db import task_session_scope
    from 最小可执行demo.domain.enums import SearchTaskStatus
    from 最小可执行demo.ports.knowledge_projection_port import ActiveDocumentRef, ActiveScope, KnowledgeProjectionReadPort, ParentDocument
    from 最小可执行demo.ports.object_storage_port import ObjectStorageReadPort
    from 最小可执行demo.infrastructure.repositories import SearchTaskRepository


class KnowledgeProjectionReader(KnowledgeProjectionReadPort):
    """Resolves active knowledge scope and retrieval filters for online search."""

    def __init__(self, object_storage: ObjectStorageReadPort) -> None:
        self.object_storage = object_storage

    async def resolve_active_scope(
        self,
        kb_code: str,
        scope_json: dict[str, Any] | None = None,
    ) -> ActiveScope:
        scope_json = scope_json or {}
        stmt = (
            select(UpstreamDocument, UpstreamDocumentVersion)
            .join(
                UpstreamDocumentVersion,
                UpstreamDocument.active_version_id == UpstreamDocumentVersion.id,
            )
            .where(UpstreamDocument.active_version_id.is_not(None))
        )

        document_ids = scope_json.get("document_ids") or []
        external_doc_keys = scope_json.get("external_doc_keys") or []
        version_ids = scope_json.get("version_ids") or []

        if document_ids:
            stmt = stmt.where(UpstreamDocument.id.in_(document_ids))
        if external_doc_keys:
            stmt = stmt.where(UpstreamDocument.external_doc_key.in_(external_doc_keys))
        if version_ids:
            stmt = stmt.where(UpstreamDocumentVersion.id.in_(version_ids))

        async with task_session_scope() as session:
            rows = (await session.execute(stmt)).all()

        documents: list[ActiveDocumentRef] = []
        active_version_ids: list[int] = []
        for document, version in rows:
            active_version_ids.append(version.id)
            documents.append(
                {
                    "document_id": document.id,
                    "external_doc_key": document.external_doc_key,
                    "title": document.title,
                    "active_version_id": version.id,
                    "storage_key": version.storage_key,
                }
            )

        return {
            "kb_code": kb_code,
            "active_version_ids": active_version_ids,
            "documents": documents,
        }

    async def build_retrieval_filters(self, task_id: int) -> dict[str, Any]:
        async with task_session_scope() as session:
            task_repo = SearchTaskRepository(session)
            task = await task_repo.get_by_id(task_id)
            if task is None:
                return {
                    "kb_code": "default",
                    "allowed_version_ids": [],
                    "document_by_version": {},
                    "external_doc_key_by_version": {},
                    "storage_key_by_version": {},
                }
            scope = await self.resolve_active_scope(task.kb_code, task.scope_json)

        document_by_version: dict[int, int] = {}
        external_doc_key_by_version: dict[int, str] = {}
        storage_key_by_version: dict[int, str] = {}
        for doc_ref in scope["documents"]:
            version_id = doc_ref["active_version_id"]
            document_by_version[version_id] = doc_ref["document_id"]
            external_doc_key_by_version[version_id] = doc_ref["external_doc_key"]
            storage_key_by_version[version_id] = doc_ref["storage_key"]

        return {
            "kb_code": task.kb_code if task is not None else "default",
            "scope_json": task.scope_json if task is not None else None,
            "allowed_version_ids": scope["active_version_ids"],
            "document_by_version": document_by_version,
            "external_doc_key_by_version": external_doc_key_by_version,
            "storage_key_by_version": storage_key_by_version,
            "task_status": task.status.value if task is not None else SearchTaskStatus.PENDING.value,
        }

    async def load_parent_document(self, locator: dict[str, Any]) -> ParentDocument:
        version_id = int(locator.get("version_id") or 0)
        storage_key = locator.get("storage_key")
        document_id = locator.get("document_id")

        if not storage_key and version_id:
            stmt = select(UpstreamDocumentVersion).where(UpstreamDocumentVersion.id == version_id)
            async with task_session_scope() as session:
                version = await session.scalar(stmt)
            if version is None:
                return {
                    "document_id": document_id,
                    "version_id": version_id,
                    "storage_key": "",
                    "content": "",
                    "metadata": {},
                }
            storage_key = version.storage_key
            document_id = document_id or version.document_id

        if not storage_key:
            return {
                "document_id": document_id,
                "version_id": version_id,
                "storage_key": "",
                "content": "",
                "metadata": {},
            }

        raw = await self.object_storage.get(storage_key)
        content = raw.decode("utf-8", errors="ignore")
        return {
            "document_id": document_id,
            "version_id": version_id,
            "storage_key": storage_key,
            "content": content,
            "metadata": {
                "locator": locator,
            },
        }


KnowledgeProjectionReadAdapter = KnowledgeProjectionReader
