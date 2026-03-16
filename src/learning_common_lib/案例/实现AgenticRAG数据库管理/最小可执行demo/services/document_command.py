"""Document write-side service: upload, delete, and manual rebuild commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..config import get_settings
    from ..enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        QueueName,
        StorageStatus,
        TaskName,
        VisibilityStatus,
    )
    from ..errors import ConflictError, NotFoundError
    from ..models import Document, DocumentVersion
    from ..repositories import DocumentRepository, VersionRepository
    from ..storage import BaseObjectStorage
    from .common import (
        build_outbox_event,
        build_parser_config_hash,
        build_storage_key,
        sha256_bytes,
        validate_upload_request,
    )
    from .outbox_dispatcher import best_effort_dispatch_outbox
except ImportError:
    from config import get_settings
    from enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        QueueName,
        StorageStatus,
        TaskName,
        VisibilityStatus,
    )
    from errors import ConflictError, NotFoundError
    from models import Document, DocumentVersion
    from repositories import DocumentRepository, VersionRepository
    from storage import BaseObjectStorage
    from services.common import (
        build_outbox_event,
        build_parser_config_hash,
        build_storage_key,
        sha256_bytes,
        validate_upload_request,
    )
    from services.outbox_dispatcher import best_effort_dispatch_outbox

logger = logging.getLogger(__name__)


@dataclass
class UploadOutcome:
    document_id: int
    version_id: int
    reused_existing_version: bool
    message: str


class DocumentCommandService:
    def __init__(self, session: AsyncSession, object_storage: BaseObjectStorage) -> None:
        self.session = session
        self.object_storage = object_storage

    async def upload_document(
        self,
        *,
        external_doc_key: str,
        title: str,
        file_name: str,
        mime_type: str,
        content: bytes,
    ) -> UploadOutcome:
        normalized_key, normalized_file_name, normalized_mime_type = validate_upload_request(
            external_doc_key=external_doc_key,
            file_name=file_name,
            mime_type=mime_type,
            content=content,
        )
        file_hash = sha256_bytes(content)
        parser_config_hash = build_parser_config_hash()

        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)

        reuse_outcome: UploadOutcome | None = None
        version_id: int | None = None
        document_id: int | None = None
        storage_key: str | None = None

        # 事务 A：只负责锁文档、分配版本号和预留 storage_key，不在事务内写对象存储。
        async with self.session.begin():
            document = await doc_repo.get_by_external_key(normalized_key, for_update=True)
            if document is None:
                document = Document(
                    external_doc_key=normalized_key,
                    title=title or normalized_file_name,
                    lifecycle_status=DocumentLifecycleStatus.ACTIVE,
                )
                self.session.add(document)
                await self.session.flush()
            else:
                if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE:
                    raise ConflictError("文档当前不允许上传新版本")
                inflight = await version_repo.find_inflight_by_document(document.id)
                if inflight is not None:
                    raise ConflictError("VERSION_IN_PROGRESS")

            current_active = None
            if document.active_version_id is not None:
                current_active = await version_repo.get_by_id(document.active_version_id)
            if current_active is not None and current_active.file_hash == file_hash:
                # 只复用“当前已激活版本”，避免把历史 superseded 版本重新当作最新版本暴露出去。
                reuse_outcome = UploadOutcome(
                    document_id=document.id,
                    version_id=current_active.id,
                    reused_existing_version=True,
                    message="命中相同 file_hash，复用当前活动版本",
                )
            else:
                next_version_no = document.latest_version_no + 1
                storage_key = build_storage_key(document.id, next_version_no, normalized_file_name)
                version = DocumentVersion(
                    document_id=document.id,
                    version_no=next_version_no,
                    file_hash=file_hash,
                    file_name=normalized_file_name,
                    file_size=len(content),
                    mime_type=normalized_mime_type,
                    storage_key=storage_key,
                    storage_status=StorageStatus.PENDING_UPLOAD,
                    parse_status=ParseStatus.PENDING,
                    index_status=IndexStatus.PENDING,
                    milvus_status=ProjectionStatus.PENDING,
                    es_status=ProjectionStatus.PENDING,
                    visibility_status=VisibilityStatus.STAGED,
                    parser_version=get_settings().parser_version,
                    parser_config_hash=parser_config_hash,
                    embedding_model=get_settings().embedding_model,
                )
                self.session.add(version)
                await self.session.flush()

                document.title = title or document.title or normalized_file_name
                document.latest_version_no = next_version_no
                document.row_version += 1

                document_id = document.id
                version_id = version.id

        if reuse_outcome is not None:
            logger.info(
                "reuse existing active version by file hash",
                extra={
                    "document_id": reuse_outcome.document_id,
                    "version_id": reuse_outcome.version_id,
                    "file_hash": file_hash,
                },
            )
            return reuse_outcome

        assert document_id is not None
        assert version_id is not None
        assert storage_key is not None

        try:
            # 对象写入后立即回读校验，确保 storage_key 指向的是完整可读对象，而不是半成功写入。
            await self.object_storage.put(storage_key, content)
            stored_bytes = await self.object_storage.get(storage_key)
            if len(stored_bytes) != len(content) or sha256_bytes(stored_bytes) != file_hash:
                raise RuntimeError("对象存储写入校验失败")
        except Exception as exc:
            # 这里选择“先删对象，再把版本打成 FAILED”，避免留下 READY 之外的脏对象。
            await self.object_storage.delete(storage_key)
            await self._mark_version_upload_failed(version_id, str(exc))
            raise

        try:
            # 事务 B：对象 ready 后再切换状态并写 PARSE_REQUESTED，避免产生脏事件。
            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                if version is None:
                    raise NotFoundError(f"version {version_id} 不存在")
                version.storage_status = StorageStatus.READY
                version.last_error_message = None
                version.row_version += 1
                self.session.add(
                    build_outbox_event(
                        aggregate_type=AggregateType.DOCUMENT_VERSION,
                        aggregate_id=version.id,
                        event_type=OutboxEventType.PARSE_REQUESTED,
                        queue_name=QueueName.PARSE,
                        task_name=TaskName.PARSE_VERSION,
                        payload_json={"version_id": version.id},
                        dedupe_key=f"parse:{version.id}",
                    )
                )
        except Exception as exc:
            # 如果事务 B 失败，宁可把对象删掉并打成失败，也不保留“对象已存在但无事件”的悬空版本。
            await self.object_storage.delete(storage_key)
            await self._mark_version_upload_failed(version_id, str(exc))
            raise

        logger.info(
            "upload accepted and parse requested",
            extra={
                "document_id": document_id,
                "version_id": version_id,
                "file_hash": file_hash,
                "storage_key": storage_key,
            },
        )
        await best_effort_dispatch_outbox()
        return UploadOutcome(
            document_id=document_id,
            version_id=version_id,
            reused_existing_version=False,
            message="上传成功，已进入解析流水线",
        )

    async def delete_document(self, document_id: int) -> None:
        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)
        async with self.session.begin():
            document = await doc_repo.get_by_id(document_id, for_update=True)
            if document is None:
                raise NotFoundError(f"document {document_id} 不存在")
            if document.lifecycle_status in {DocumentLifecycleStatus.DELETING, DocumentLifecycleStatus.DELETED}:
                return

            document.lifecycle_status = DocumentLifecycleStatus.DELETING
            document.active_version_id = None
            document.row_version += 1

            versions = await version_repo.list_versions_for_document_cleanup(document.id)
            for version in versions:
                version.visibility_status = VisibilityStatus.DELETE_PENDING
                if version.storage_status != StorageStatus.DELETED:
                    version.storage_status = StorageStatus.DELETE_PENDING
                version.row_version += 1
                self.session.add(
                    build_outbox_event(
                        aggregate_type=AggregateType.DOCUMENT_VERSION,
                        aggregate_id=version.id,
                        event_type=OutboxEventType.CLEAN_REQUESTED,
                        queue_name=QueueName.CLEAN,
                        task_name=TaskName.CLEAN_VERSION,
                        payload_json={"version_id": version.id},
                        dedupe_key=f"clean:{version.id}:delete",
                    )
                )

        logger.info("document delete requested", extra={"document_id": document_id})
        await best_effort_dispatch_outbox()

    async def request_rebuild(self, version_id: int) -> None:
        version_repo = VersionRepository(self.session)
        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            self.session.add(
                build_outbox_event(
                    aggregate_type=AggregateType.DOCUMENT_VERSION,
                    aggregate_id=version.id,
                    event_type=OutboxEventType.REBUILD_REQUESTED,
                    queue_name=QueueName.INDEX,
                    task_name=TaskName.INDEX_VERSION,
                    payload_json={"version_id": version.id},
                    dedupe_key=f"manual-rebuild:{version.id}:{uuid4().hex}",
                )
            )

        logger.info("manual rebuild requested", extra={"version_id": version_id})
        await best_effort_dispatch_outbox()

    async def _mark_version_upload_failed(self, version_id: int, error_message: str) -> None:
        await self.session.rollback()
        version_repo = VersionRepository(self.session)
        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                return
            version.storage_status = StorageStatus.FAILED
            version.parse_status = ParseStatus.FAILED
            version.index_status = IndexStatus.FAILED
            version.last_error_message = error_message[:1024]
            version.row_version += 1
