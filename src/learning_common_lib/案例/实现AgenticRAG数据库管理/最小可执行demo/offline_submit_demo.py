from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

try:
    from .bootstrap import build_object_storage
    from .db import create_tables, session_scope
    from .enums import DocumentLifecycleStatus, IndexStatus, ParseStatus, VisibilityStatus
    from .repositories import DocumentRepository, VersionRepository
    from .services import DocumentCommandService
except ImportError:
    from bootstrap import build_object_storage
    from db import create_tables, session_scope
    from enums import DocumentLifecycleStatus, IndexStatus, ParseStatus, VisibilityStatus
    from repositories import DocumentRepository, VersionRepository
    from services import DocumentCommandService

logger = logging.getLogger(__name__)


@dataclass
class VersionSnapshot:
    version_id: int
    version_no: int
    parse_status: str
    index_status: str
    milvus_status: str
    es_status: str
    visibility_status: str
    retry_count: int
    last_error_message: str | None


@dataclass
class DocumentSnapshot:
    document_id: int
    external_doc_key: str
    lifecycle_status: str
    active_version_id: int | None
    latest_version_no: int
    versions: list[VersionSnapshot]


async def load_document_snapshot(document_id: int) -> DocumentSnapshot:
    async with session_scope() as session:
        doc_repo = DocumentRepository(session)
        version_repo = VersionRepository(session)
        document = await doc_repo.get_by_id(document_id)
        if document is None:
            raise RuntimeError(f"document {document_id} not found")
        versions = await version_repo.list_by_document(document_id)
        return DocumentSnapshot(
            document_id=document.id,
            external_doc_key=document.external_doc_key,
            lifecycle_status=document.lifecycle_status.value,
            active_version_id=document.active_version_id,
            latest_version_no=document.latest_version_no,
            versions=[
                VersionSnapshot(
                    version_id=version.id,
                    version_no=version.version_no,
                    parse_status=version.parse_status.value,
                    index_status=version.index_status.value,
                    milvus_status=version.milvus_status.value,
                    es_status=version.es_status.value,
                    visibility_status=version.visibility_status.value,
                    retry_count=version.retry_count,
                    last_error_message=version.last_error_message,
                )
                for version in versions
            ],
        )


def is_upload_finished(snapshot: DocumentSnapshot) -> bool:
    if snapshot.active_version_id is None:
        return False
    active = next((item for item in snapshot.versions if item.version_id == snapshot.active_version_id), None)
    if active is None:
        return False
    return (
        active.parse_status == ParseStatus.SUCCESS.value
        and active.index_status == IndexStatus.SUCCESS.value
        and active.visibility_status == VisibilityStatus.ACTIVE.value
    )


def is_delete_finished(snapshot: DocumentSnapshot) -> bool:
    return snapshot.lifecycle_status == DocumentLifecycleStatus.DELETED.value


async def wait_until(
    document_id: int,
    *,
    label: str,
    predicate,
    timeout_seconds: int = 60,
    interval_seconds: int = 2,
) -> DocumentSnapshot:
    loops = max(timeout_seconds // interval_seconds, 1)
    last_snapshot: DocumentSnapshot | None = None
    for _ in range(loops):
        snapshot = await load_document_snapshot(document_id)
        last_snapshot = snapshot
        logger.info("%s: %s", label, asdict(snapshot))
        if predicate(snapshot):
            return snapshot
        await asyncio.sleep(interval_seconds)
    raise TimeoutError(f"{label} timeout, last_snapshot={asdict(last_snapshot) if last_snapshot else None}")


async def submit_upload() -> tuple[int, int]:
    external_doc_key = f"offline-demo-doc-{uuid4().hex[:8]}"
    async with session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        outcome = await service.upload_document(
            external_doc_key=external_doc_key,
            title="离线提交测试文档",
            file_name="offline-demo.txt",
            mime_type="text/plain",
            content=(
                "这是一个离线脚本提交的测试文档。\n"
                "如果 worker 正常运行，它应该被解析、切片、索引，并最终切换为活动版本。\n"
                "这段文本足够让最小 demo 产生至少一个 chunk。\n"
            ).encode("utf-8"),
        )
        logger.info("upload submitted: %s", outcome)
        return outcome.document_id, outcome.version_id


async def submit_delete(document_id: int) -> None:
    async with session_scope() as session:
        service = DocumentCommandService(session, build_object_storage())
        await service.delete_document(document_id)
        logger.info("delete submitted: document_id=%s", document_id)


async def main() -> None:
    await create_tables()

    document_id, version_id = await submit_upload()
    logger.info("waiting upload pipeline: document_id=%s version_id=%s", document_id, version_id)
    final_upload_snapshot = await wait_until(
        document_id,
        label="upload_pipeline",
        predicate=is_upload_finished,
        timeout_seconds=90,
        interval_seconds=2,
    )
    logger.info("upload finished: %s", asdict(final_upload_snapshot))

    await submit_delete(document_id)
    logger.info("waiting cleanup pipeline: document_id=%s", document_id)
    final_delete_snapshot = await wait_until(
        document_id,
        label="delete_pipeline",
        predicate=is_delete_finished,
        timeout_seconds=90,
        interval_seconds=2,
    )
    logger.info("delete finished: %s", asdict(final_delete_snapshot))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(main())
