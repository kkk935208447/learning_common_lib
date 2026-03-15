from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .bootstrap import (
        build_embedding_provider,
        build_lock_port,
        build_object_storage,
        build_search_store,
        build_task_queue,
        build_vector_store,
    )
    from .config import get_settings
    from .db import session_scope
    from .embedding import BaseEmbeddingProvider
    from .enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        PublishStatus,
        QueueName,
        TaskName,
        VisibilityStatus,
    )
    from .errors import ConflictError, NotFoundError, RetryableTaskError, ValidationError
    from .models import Document, DocumentChunk, DocumentVersion, OutboxEvent
    from .repositories import ChunkRepository, DocumentRepository, OutboxRepository, VersionRepository
    from .search_store import BaseSearchStore
    from .storage import BaseObjectStorage
    from .task_queue import BaseTaskQueue
    from .vector_store import BaseVectorStore
except ImportError:
    from bootstrap import (
        build_embedding_provider,
        build_lock_port,
        build_object_storage,
        build_search_store,
        build_task_queue,
        build_vector_store,
    )
    from config import get_settings
    from db import session_scope
    from embedding import BaseEmbeddingProvider
    from enums import (
        AggregateType,
        DocumentLifecycleStatus,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        PublishStatus,
        QueueName,
        TaskName,
        VisibilityStatus,
    )
    from errors import ConflictError, NotFoundError, RetryableTaskError, ValidationError
    from models import Document, DocumentChunk, DocumentVersion, OutboxEvent
    from repositories import ChunkRepository, DocumentRepository, OutboxRepository, VersionRepository
    from search_store import BaseSearchStore
    from storage import BaseObjectStorage
    from task_queue import BaseTaskQueue
    from vector_store import BaseVectorStore

logger = logging.getLogger(__name__)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_parser_config_hash() -> str:
    settings = get_settings()
    raw = json.dumps(
        {
            "chunk_size": settings.parser_chunk_size,
            "chunk_overlap": settings.parser_chunk_overlap,
            "parser_version": settings.parser_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha256_text(raw)


def chunk_text(content: str) -> list[str]:
    settings = get_settings()
    chunk_size = settings.parser_chunk_size
    overlap = settings.parser_chunk_overlap
    if chunk_size <= overlap:
        raise ValidationError("chunk_size 必须大于 chunk_overlap")

    stripped = content.strip()
    if not stripped:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(len(stripped), start + chunk_size)
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def parse_bytes_to_text(content: bytes, mime_type: str) -> str:
    # 最小 demo 只做文本解码，非文本文件直接宽松解码。
    if mime_type.startswith("text/") or mime_type in {"application/json", "application/xml"}:
        return content.decode("utf-8", errors="ignore")
    return content.decode("utf-8", errors="ignore")


def next_retry_delay(retries: int) -> int:
    settings = get_settings()
    return settings.task_retry_base_seconds * (2 ** max(retries - 1, 0))


def build_outbox_event(
    *,
    aggregate_type: AggregateType,
    aggregate_id: int,
    event_type: OutboxEventType,
    queue_name: QueueName,
    task_name: TaskName,
    payload_json: dict[str, Any],
    dedupe_key: str,
) -> OutboxEvent:
    return OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        queue_name=queue_name.value,
        task_name=task_name.value,
        payload_json=payload_json,
        dedupe_key=dedupe_key,
        publish_status=PublishStatus.PENDING,
        available_at=datetime.utcnow(),
    )


def should_dispatch_event(*, publish_status: PublishStatus, next_retry_at: datetime | None) -> bool:
    if publish_status == PublishStatus.PENDING:
        return True
    if publish_status == PublishStatus.FAILED:
        if next_retry_at is None:
            return True
        return next_retry_at <= datetime.utcnow()
    return False


@dataclass
class UploadOutcome:
    document_id: int
    version_id: int
    reused_existing_version: bool
    message: str


class OutboxDispatcherService:
    # 这里保持“先提交业务事务，再派发任务”的简单模型。
    def __init__(self, session: AsyncSession, task_queue: BaseTaskQueue) -> None:
        self.session = session
        self.task_queue = task_queue

    async def dispatch_pending(self, limit: int = 100) -> int:
        repo = OutboxRepository(self.session)
        sent = 0
        dispatched_events: list[dict[str, Any]] = []
        events = await repo.list_ready(limit)
        event_snapshots = [
            {
                "event_id": event.id,
                "task_name": event.task_name,
                "payload_json": event.payload_json,
                "queue_name": event.queue_name,
                "publish_status": event.publish_status,
                "next_retry_at": event.next_retry_at,
            }
            for event in events
        ]
        await self.session.rollback()
        for event in event_snapshots:
            if not should_dispatch_event(
                publish_status=event["publish_status"],
                next_retry_at=event["next_retry_at"],
            ):
                continue
            dispatched_events.append(
                {
                    "event_id": event["event_id"],
                    "task_name": event["task_name"],
                    "payload_json": event["payload_json"],
                    "queue_name": event["queue_name"],
                }
            )

        for event in dispatched_events:
            try:
                if get_settings().celery_eager:
                    await execute_local_task(
                        task_name=event["task_name"],
                        payload=event["payload_json"],
                    )
                else:
                    await asyncio.to_thread(
                        self.task_queue.dispatch,
                        task_name=event["task_name"],
                        payload=event["payload_json"],
                        queue_name=event["queue_name"],
                    )
                sent += 1
                async with self.session.begin():
                    sent_event = await self.session.get(OutboxEvent, event["event_id"], with_for_update=True)
                    if sent_event is not None:
                        sent_event.publish_status = PublishStatus.SENT
                        sent_event.published_at = datetime.utcnow()
                        sent_event.next_retry_at = None
            except Exception as exc:
                logger.warning(
                    "dispatch pending task failed",
                    extra={"task_name": event["task_name"], "error": str(exc)},
                )
                async with self.session.begin():
                    failed_event = await self.session.get(OutboxEvent, event["event_id"], with_for_update=True)
                    if failed_event is not None:
                        failed_event.publish_status = PublishStatus.FAILED
                        failed_event.next_retry_at = datetime.utcnow() + timedelta(
                            seconds=get_settings().task_retry_base_seconds
                        )
        return sent

    async def cleanup_sent_history(self) -> int:
        repo = OutboxRepository(self.session)
        async with self.session.begin():
            return await repo.cleanup_sent_older_than(get_settings().outbox_cleanup_days)


async def best_effort_dispatch_outbox(limit: int = 100) -> None:
    settings = get_settings()
    lock = None
    token = None
    if not settings.celery_eager:
        lock = build_lock_port()
        token = await asyncio.to_thread(lock.try_lock, "rag:outbox:dispatcher", settings.lock_ttl_seconds)
        if token is None:
            logger.info("skip best effort dispatch because dispatcher lock is held")
            return None
    try:
        async with session_scope() as session:
            dispatcher = OutboxDispatcherService(session, build_task_queue())
            count = await dispatcher.dispatch_pending(limit=limit)
            logger.info("best effort dispatch outbox finished", extra={"sent": count})
    except Exception as exc:
        logger.warning("best effort dispatch outbox failed: %s", exc)
        return None
    finally:
        if lock is not None and token is not None:
            await asyncio.to_thread(lock.release, "rag:outbox:dispatcher", token)


async def execute_local_task(task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with session_scope() as session:
        if task_name == TaskName.PARSE_VERSION.value:
            service = ParsePipelineService(session, build_object_storage())
            return await service.run(payload["version_id"])
        if task_name == TaskName.INDEX_VERSION.value:
            service = IndexPipelineService(
                session,
                build_vector_store(),
                build_search_store(),
                build_embedding_provider(),
            )
            return await service.run(payload["version_id"])
        if task_name == TaskName.CLEAN_VERSION.value:
            service = CleanupService(
                session,
                build_object_storage(),
                build_vector_store(),
                build_search_store(),
            )
            return await service.run(payload["version_id"])
        if task_name == TaskName.JANITOR_SCAN.value:
            service = JanitorService(session, build_vector_store(), build_search_store())
            return await service.run_once()
        raise ValidationError(f"未知 task_name: {task_name}")


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
        if not external_doc_key.strip():
            raise ValidationError("external_doc_key 不能为空")

        file_hash = sha256_bytes(content)
        parser_config_hash = build_parser_config_hash()
        storage_key = f"raw/{uuid4().hex}_{Path(file_name).name}"
        await self.object_storage.put(storage_key, content)
        reuse_outcome: UploadOutcome | None = None

        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)
        try:
            async with self.session.begin():
                document = await doc_repo.get_by_external_key(external_doc_key, for_update=True)
                if document is None:
                    document = Document(
                        external_doc_key=external_doc_key,
                        title=title or file_name,
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
                # 同一个逻辑文档上传相同内容时，直接复用当前活动版本。
                if current_active is not None and current_active.file_hash == file_hash:
                    reuse_outcome = UploadOutcome(
                        document_id=document.id,
                        version_id=current_active.id,
                        reused_existing_version=True,
                        message="命中相同 file_hash，复用当前活动版本",
                    )
                else:
                    next_version_no = document.latest_version_no + 1
                    version = DocumentVersion(
                        document_id=document.id,
                        version_no=next_version_no,
                        file_hash=file_hash,
                        file_name=file_name,
                        file_size=len(content),
                        mime_type=mime_type or "application/octet-stream",
                        storage_key=storage_key,
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

                    document.title = title or document.title or file_name
                    document.latest_version_no = next_version_no
                    document.row_version += 1

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
        except Exception:
            await self.object_storage.delete(storage_key)
            raise

        if reuse_outcome is not None:
            await self.object_storage.delete(storage_key)
            return reuse_outcome

        await best_effort_dispatch_outbox()
        return UploadOutcome(
            document_id=document.id,
            version_id=version.id,
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

            document.lifecycle_status = DocumentLifecycleStatus.DELETING
            document.active_version_id = None
            document.row_version += 1

            versions = await version_repo.list_versions_for_document_cleanup(document.id)
            for version in versions:
                version.visibility_status = VisibilityStatus.DELETE_PENDING
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

        await best_effort_dispatch_outbox()


class ParsePipelineService:
    def __init__(self, session: AsyncSession, object_storage: BaseObjectStorage) -> None:
        self.session = session
        self.object_storage = object_storage

    async def run(self, version_id: int) -> dict[str, Any]:
        version_repo = VersionRepository(self.session)
        chunk_repo = ChunkRepository(self.session)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            if version.parse_status == ParseStatus.SUCCESS:
                return {"version_id": version_id, "status": "already_parsed"}
            version.parse_status = ParseStatus.RUNNING
            version.row_version += 1

        try:
            raw_bytes = await self.object_storage.get(version.storage_key)
            if version.parser_config_hash != build_parser_config_hash():
                raise ValidationError("parser_config_hash 不匹配，拒绝原地重跑")
            text = parse_bytes_to_text(raw_bytes, version.mime_type)
            # 缩减版 demo 只做最简单的文本切片，不引入复杂解析器树。
            chunk_texts = chunk_text(text)
            chunks = [
                DocumentChunk(
                    version_id=version.id,
                    chunk_uid=f"chunk:{version.id}:{idx}",
                    chunk_no=idx,
                    chunk_hash=sha256_text(chunk_text_value),
                    content=chunk_text_value,
                    metadata_json={
                        "version_id": version.id,
                        "chunk_no": idx,
                        "file_name": version.file_name,
                        "mime_type": version.mime_type,
                    },
                )
                for idx, chunk_text_value in enumerate(chunk_texts, start=1)
            ]

            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                await chunk_repo.replace_for_version(version_id, chunks)
                version.chunk_count = len(chunks)
                version.parse_status = ParseStatus.SUCCESS
                version.index_status = IndexStatus.PENDING
                version.milvus_status = ProjectionStatus.PENDING
                version.es_status = ProjectionStatus.PENDING
                version.last_error_message = None
                version.retry_count = 0
                version.row_version += 1
                self.session.add(
                    build_outbox_event(
                        aggregate_type=AggregateType.DOCUMENT_VERSION,
                        aggregate_id=version.id,
                        event_type=OutboxEventType.INDEX_REQUESTED,
                        queue_name=QueueName.INDEX,
                        task_name=TaskName.INDEX_VERSION,
                        payload_json={"version_id": version.id},
                        dedupe_key=f"index:{version.id}",
                    )
                )
            await best_effort_dispatch_outbox()
            return {"version_id": version_id, "chunk_count": len(chunks), "status": "parsed"}
        except Exception as exc:
            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                if version is not None:
                    version.parse_status = ParseStatus.FAILED
                    version.retry_count += 1
                    version.last_error_message = str(exc)[:1024]
                    version.row_version += 1
            raise


class IndexPipelineService:
    def __init__(
        self,
        session: AsyncSession,
        vector_store: BaseVectorStore,
        search_store: BaseSearchStore,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        self.session = session
        self.vector_store = vector_store
        self.search_store = search_store
        self.embedding_provider = embedding_provider

    async def run(self, version_id: int) -> dict[str, Any]:
        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)
        chunk_repo = ChunkRepository(self.session)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            if version.parse_status != ParseStatus.SUCCESS:
                raise ValidationError("版本尚未解析成功，不能建立索引")
            if version.index_status == IndexStatus.SUCCESS and version.visibility_status == VisibilityStatus.ACTIVE:
                return {"version_id": version_id, "status": "already_indexed"}
            version.index_status = IndexStatus.RUNNING
            version.row_version += 1

        try:
            # 这里先把当前版本的 chunks 读出来，再去写 mock 向量库和检索库。
            async with self.session.begin():
                chunks = await chunk_repo.list_by_version(version_id)

            vectors = await self.embedding_provider.embed([chunk.content for chunk in chunks])
            vector_records = [
                {
                    "chunk_uid": chunk.chunk_uid,
                    "version_id": version_id,
                    "vector": vector,
                    "content_preview": chunk.content[:120],
                    "metadata": chunk.metadata_json,
                }
                for chunk, vector in zip(chunks, vectors, strict=False)
            ]
            search_docs = [
                {
                    "chunk_uid": chunk.chunk_uid,
                    "version_id": version_id,
                    "content": chunk.content,
                    "metadata": chunk.metadata_json,
                }
                for chunk in chunks
            ]
            await self.vector_store.upsert_chunks(version_id, vector_records)
            await self.search_store.upsert_chunks(version_id, search_docs)

            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                document = await doc_repo.get_by_id(version.document_id, for_update=True)
                old_active_version_id = document.active_version_id

                version.index_status = IndexStatus.SUCCESS
                version.milvus_status = ProjectionStatus.SUCCESS
                version.es_status = ProjectionStatus.SUCCESS
                version.visibility_status = VisibilityStatus.ACTIVE
                version.retry_count = 0
                version.last_error_message = None
                version.row_version += 1

                document.active_version_id = version.id
                document.row_version += 1
                if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE:
                    document.lifecycle_status = DocumentLifecycleStatus.ACTIVE

                if old_active_version_id is not None and old_active_version_id != version.id:
                    old_version = await version_repo.get_by_id(old_active_version_id, for_update=True)
                    if old_version is not None and old_version.visibility_status != VisibilityStatus.DELETE_PENDING:
                        old_version.visibility_status = VisibilityStatus.SUPERSEDED
                        old_version.row_version += 1
                        self.session.add(
                            build_outbox_event(
                                aggregate_type=AggregateType.DOCUMENT_VERSION,
                                aggregate_id=old_version.id,
                                event_type=OutboxEventType.CLEAN_REQUESTED,
                                queue_name=QueueName.CLEAN,
                                task_name=TaskName.CLEAN_VERSION,
                                payload_json={"version_id": old_version.id},
                                dedupe_key=f"clean:{old_version.id}:superseded",
                            )
                        )
            await best_effort_dispatch_outbox()
            return {"version_id": version_id, "status": "indexed", "chunk_count": len(chunks)}
        except Exception as exc:
            await self.vector_store.delete_by_version(version_id)
            await self.search_store.delete_by_version(version_id)
            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                if version is not None:
                    version.index_status = IndexStatus.FAILED
                    version.milvus_status = ProjectionStatus.FAILED
                    version.es_status = ProjectionStatus.FAILED
                    version.retry_count += 1
                    version.last_error_message = str(exc)[:1024]
                    version.row_version += 1
            raise


class CleanupService:
    def __init__(
        self,
        session: AsyncSession,
        object_storage: BaseObjectStorage,
        vector_store: BaseVectorStore,
        search_store: BaseSearchStore,
    ) -> None:
        self.session = session
        self.object_storage = object_storage
        self.vector_store = vector_store
        self.search_store = search_store

    async def run(self, version_id: int) -> dict[str, Any]:
        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            storage_key = version.storage_key

        await self.vector_store.delete_by_version(version_id)
        await self.search_store.delete_by_version(version_id)
        await self.object_storage.delete(storage_key)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            document = await doc_repo.get_by_id(version.document_id, for_update=True)
            version.milvus_status = ProjectionStatus.DELETED
            version.es_status = ProjectionStatus.DELETED
            version.row_version += 1

            if version.visibility_status == VisibilityStatus.DELETE_PENDING:
                version.visibility_status = VisibilityStatus.DELETED

            versions = await version_repo.list_by_document(document.id)
            if versions and all(v.visibility_status == VisibilityStatus.DELETED for v in versions):
                document.lifecycle_status = DocumentLifecycleStatus.DELETED
                document.deleted_at = datetime.utcnow()
                document.row_version += 1

        return {"version_id": version_id, "status": "cleaned"}


class JanitorService:
    def __init__(
        self,
        session: AsyncSession,
        vector_store: BaseVectorStore,
        search_store: BaseSearchStore,
    ) -> None:
        self.session = session
        self.vector_store = vector_store
        self.search_store = search_store

    async def run_once(self, limit: int | None = None) -> dict[str, Any]:
        limit = limit or get_settings().janitor_scan_limit
        version_repo = VersionRepository(self.session)
        chunk_repo = ChunkRepository(self.session)
        rebuild_count = 0

        active_versions = await version_repo.list_active_versions(limit)
        versions_to_rebuild: list[int] = []
        for version in active_versions:
            mysql_count = await chunk_repo.count_by_version(version.id)
            vector_count = await self.vector_store.count_by_version(version.id)
            search_count = await self.search_store.count_by_version(version.id)
            if mysql_count != vector_count or mysql_count != search_count:
                versions_to_rebuild.append(version.id)

        await self.session.rollback()
        async with self.session.begin():
            for version_id in versions_to_rebuild:
                rebuild_count += 1
                self.session.add(
                    build_outbox_event(
                        aggregate_type=AggregateType.DOCUMENT_VERSION,
                        aggregate_id=version_id,
                        event_type=OutboxEventType.REBUILD_REQUESTED,
                        queue_name=QueueName.INDEX,
                        task_name=TaskName.INDEX_VERSION,
                        payload_json={"version_id": version_id},
                        dedupe_key=f"rebuild:{version_id}:{uuid4().hex}",
                    )
                )

        if rebuild_count:
            await best_effort_dispatch_outbox()
        return {"scanned": len(active_versions), "rebuild_requested": rebuild_count}
