"""Parse pipeline that reads source objects and materializes MySQL chunks."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..enums import (
        AggregateType,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        QueueName,
        StorageStatus,
        TaskName,
    )
    from ..errors import NotFoundError, ValidationError
    from ..models import DocumentChunk
    from ..repositories import ChunkRepository, VersionRepository
    from ..storage import BaseObjectStorage
    from .common import (
        build_outbox_event,
        build_parser_config_hash,
        chunk_text,
        parse_bytes_to_text,
        sha256_text,
    )
    from .outbox_dispatcher import best_effort_dispatch_outbox
except ImportError:
    from enums import (
        AggregateType,
        IndexStatus,
        OutboxEventType,
        ParseStatus,
        ProjectionStatus,
        QueueName,
        StorageStatus,
        TaskName,
    )
    from errors import NotFoundError, ValidationError
    from models import DocumentChunk
    from repositories import ChunkRepository, VersionRepository
    from storage import BaseObjectStorage
    from services.common import (
        build_outbox_event,
        build_parser_config_hash,
        chunk_text,
        parse_bytes_to_text,
        sha256_text,
    )
    from services.outbox_dispatcher import best_effort_dispatch_outbox

logger = logging.getLogger(__name__)


# ParsePipelineService 负责把 READY 源文件转成 MySQL chunk 事实数据。
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
            if version.storage_status != StorageStatus.READY:
                raise ValidationError("版本源文件尚未就绪，不能开始解析")
            if version.parse_status == ParseStatus.SUCCESS:
                return {"version_id": version_id, "status": "already_parsed"}
            # 先把状态切到 RUNNING，再离开事务做对象读取和解析计算。
            version.parse_status = ParseStatus.RUNNING
            version.row_version += 1

        try:
            raw_bytes = await self.object_storage.get(version.storage_key)
            if version.parser_config_hash != build_parser_config_hash():
                # 同一 version_id 必须对应稳定的 parser 配置，否则会破坏幂等语义。
                raise ValidationError("parser_config_hash 不匹配，拒绝原地重跑")

            text = parse_bytes_to_text(raw_bytes, version.mime_type)
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
                if version is None:
                    raise NotFoundError(f"version {version_id} 不存在")
                # replace_for_version 保证重复解析时不会把旧 chunks 和新 chunks 混在一起。
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

            logger.info("parse finished", extra={"version_id": version_id, "chunk_count": len(chunks)})
            await best_effort_dispatch_outbox()
            return {"version_id": version_id, "chunk_count": len(chunks), "status": "parsed"}
        except Exception as exc:
            # 失败时只回写状态和错误信息，不在这里吞异常，交给 task 层决定是否重试。
            async with self.session.begin():
                version = await version_repo.get_by_id(version_id, for_update=True)
                if version is not None:
                    version.parse_status = ParseStatus.FAILED
                    version.retry_count += 1
                    version.last_error_message = str(exc)[:1024]
                    version.row_version += 1
            logger.warning("parse failed: %s", exc, extra={"version_id": version_id})
            raise
