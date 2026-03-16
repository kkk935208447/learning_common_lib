"""Thin repository helpers that keep repeated ORM queries out of services."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .enums import IndexStatus, ParseStatus, PublishStatus, StorageStatus, VisibilityStatus
    from .models import Document, DocumentChunk, DocumentVersion, OutboxEvent
except ImportError:
    from enums import IndexStatus, ParseStatus, PublishStatus, StorageStatus, VisibilityStatus
    from models import Document, DocumentChunk, DocumentVersion, OutboxEvent


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class DocumentRepository(BaseRepository):
    async def get_by_id(self, document_id: int, *, for_update: bool = False) -> Document | None:
        stmt = select(Document).where(Document.id == document_id)
        if for_update:
            # 需要修改文档主状态时，再由调用方显式申请行锁。
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_by_external_key(
        self,
        external_doc_key: str,
        *,
        for_update: bool = False,
    ) -> Document | None:
        stmt = select(Document).where(Document.external_doc_key == external_doc_key)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)


class VersionRepository(BaseRepository):
    async def get_by_id(self, version_id: int, *, for_update: bool = False) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(DocumentVersion.id == version_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_document(self, document_id: int) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def find_inflight_by_document(self, document_id: int) -> DocumentVersion | None:
        # 只要版本仍停留在 STAGED 且上传/解析/索引任一阶段未完成，就算“在途版本”。
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .where(DocumentVersion.visibility_status == VisibilityStatus.STAGED)
            .where(
                (DocumentVersion.storage_status == StorageStatus.PENDING_UPLOAD)
                | (DocumentVersion.parse_status.in_((ParseStatus.PENDING, ParseStatus.RUNNING)))
                | (DocumentVersion.index_status.in_((IndexStatus.PENDING, IndexStatus.RUNNING)))
            )
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_versions_for_document_cleanup(self, document_id: int) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .where(DocumentVersion.visibility_status != VisibilityStatus.DELETED)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_active_versions(self, limit: int) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.visibility_status == VisibilityStatus.ACTIVE)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_by_parse_status(self, status: ParseStatus) -> int:
        stmt = select(func.count(DocumentVersion.id)).where(DocumentVersion.parse_status == status)
        return int((await self.session.scalar(stmt)) or 0)

    async def count_by_index_status(self, status: IndexStatus) -> int:
        stmt = select(func.count(DocumentVersion.id)).where(DocumentVersion.index_status == status)
        return int((await self.session.scalar(stmt)) or 0)

    async def count_active(self) -> int:
        stmt = select(func.count(DocumentVersion.id)).where(DocumentVersion.visibility_status == VisibilityStatus.ACTIVE)
        return int((await self.session.scalar(stmt)) or 0)


class ChunkRepository(BaseRepository):
    async def replace_for_version(self, version_id: int, chunks: list[DocumentChunk]) -> None:
        await self.session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version_id))
        self.session.add_all(chunks)

    async def list_by_version(self, version_id: int) -> list[DocumentChunk]:
        stmt = select(DocumentChunk).where(DocumentChunk.version_id == version_id).order_by(DocumentChunk.chunk_no.asc())
        return list((await self.session.scalars(stmt)).all())

    async def count_by_version(self, version_id: int) -> int:
        chunks = await self.list_by_version(version_id)
        return len(chunks)


class OutboxRepository(BaseRepository):
    async def list_ready(self, limit: int) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.publish_status.in_((PublishStatus.PENDING, PublishStatus.FAILED)))
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_pending(self, limit: int) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.publish_status.in_((PublishStatus.PENDING, PublishStatus.FAILED)))
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_pending(self) -> int:
        stmt = select(func.count(OutboxEvent.id)).where(
            OutboxEvent.publish_status.in_((PublishStatus.PENDING, PublishStatus.FAILED))
        )
        return int((await self.session.scalar(stmt)) or 0)

    async def cleanup_sent_older_than(self, days: int) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            delete(OutboxEvent)
            .where(OutboxEvent.publish_status == PublishStatus.SENT)
            .where(OutboxEvent.published_at.is_not(None))
            .where(OutboxEvent.published_at < cutoff)
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)
