"""Index pipeline that projects parsed chunks into vector and search stores."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..embedding import BaseEmbeddingProvider
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
    from ..errors import NotFoundError, ValidationError
    from ..repositories import ChunkRepository, DocumentRepository, VersionRepository
    from ..search_store import BaseSearchStore
    from ..vector_store import BaseVectorStore
    from .common import build_outbox_event
    from .outbox_dispatcher import best_effort_dispatch_outbox
except ImportError:
    from embedding import BaseEmbeddingProvider
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
    from errors import NotFoundError, ValidationError
    from repositories import ChunkRepository, DocumentRepository, VersionRepository
    from search_store import BaseSearchStore
    from vector_store import BaseVectorStore
    from services.common import build_outbox_event
    from services.outbox_dispatcher import best_effort_dispatch_outbox

logger = logging.getLogger(__name__)


# IndexPipelineService 负责把 MySQL chunks 投影到向量库和搜索库，并切换 active version。
class IndexPipelineService:
    def __init__(
        self,
        session: AsyncSession,
        vector_store: BaseVectorStore,
        search_store: BaseSearchStore,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        # 这里同时注入三类依赖，强调 index 过程本质是“从事实表生成多份投影”。
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
            if version.storage_status != StorageStatus.READY:
                raise ValidationError("版本源文件尚未就绪，不能建立索引")
            if version.parse_status != ParseStatus.SUCCESS:
                raise ValidationError("版本尚未解析成功，不能建立索引")
            if version.index_status == IndexStatus.SUCCESS and version.visibility_status == VisibilityStatus.ACTIVE:
                # 已经切活的成功版本无需重复索引，除非走手工 rebuild 重新投递。
                return {"version_id": version_id, "status": "already_indexed"}
            # 先占住 RUNNING 状态，避免多个 worker 同时认为自己是“第一个索引者”。
            version.index_status = IndexStatus.RUNNING
            version.row_version += 1

        try:
            async with self.session.begin():
                # chunk 读取仍然走数据库事实表，而不是依赖 parser 的中间内存结果。
                chunks = await chunk_repo.list_by_version(version_id)
            # 投影写入放在事务外，避免把外部 IO 包进数据库锁窗口。
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
            # 搜索投影和向量投影共享同一批 chunk 事实，但写入结构各自独立。
            search_docs = [
                {
                    "chunk_uid": chunk.chunk_uid,
                    "version_id": version_id,
                    "content": chunk.content,
                    "metadata": chunk.metadata_json,
                }
                for chunk in chunks
            ]
            # demo 里的双写顺序并不重要，关键是两边都成功后才允许切 active_version。
            await self.vector_store.upsert_chunks(version_id, vector_records)
            await self.search_store.upsert_chunks(version_id, search_docs)

            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                if version is None:
                    raise NotFoundError(f"version {version_id} 不存在")
                document = await doc_repo.get_by_id(version.document_id, for_update=True)
                if document is None:
                    raise NotFoundError(f"document {version.document_id} 不存在")

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
                    # 即使之前文档处于其他状态，只要新版本成功切活，就恢复为 ACTIVE。
                    document.lifecycle_status = DocumentLifecycleStatus.ACTIVE

                if old_active_version_id is not None and old_active_version_id != version.id:
                    old_version = await version_repo.get_by_id(old_active_version_id, for_update=True)
                    if old_version is not None and old_version.visibility_status != VisibilityStatus.DELETE_PENDING:
                        # 只有新版本已经切活后，才异步回收旧版本，保证查询面先看到新版本。
                        old_version.visibility_status = VisibilityStatus.SUPERSEDED
                        if old_version.storage_status == StorageStatus.READY:
                            old_version.storage_status = StorageStatus.DELETE_PENDING
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

            logger.info("index finished", extra={"version_id": version_id, "chunk_count": len(chunks)})
            await best_effort_dispatch_outbox()
            return {"version_id": version_id, "status": "indexed", "chunk_count": len(chunks)}
        except Exception as exc:
            # 清理半成功投影是 index 失败补偿的核心，否则 Janitor 只能看到持续脏数据。
            # 一旦索引链路失败，先尽力删除已写入的投影，避免 Janitor 看到“半成功”状态。
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
            logger.warning("index failed: %s", exc, extra={"version_id": version_id})
            raise
