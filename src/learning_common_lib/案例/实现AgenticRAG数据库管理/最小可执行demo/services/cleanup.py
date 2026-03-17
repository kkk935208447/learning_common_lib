"""Cleanup pipeline that removes projections and source objects for old versions."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..enums import DocumentLifecycleStatus, ProjectionStatus, StorageStatus, VisibilityStatus
    from ..errors import NotFoundError
    from ..repositories import DocumentRepository, VersionRepository
    from ..search_store import BaseSearchStore
    from ..storage import BaseObjectStorage
    from ..vector_store import BaseVectorStore
    from .common import utcnow
except ImportError:
    from enums import DocumentLifecycleStatus, ProjectionStatus, StorageStatus, VisibilityStatus
    from errors import NotFoundError
    from repositories import DocumentRepository, VersionRepository
    from search_store import BaseSearchStore
    from storage import BaseObjectStorage
    from vector_store import BaseVectorStore
    from services.common import utcnow

logger = logging.getLogger(__name__)


# CleanupService 负责异步回收旧版本或已删除文档关联的所有外部资源。
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

    async def run(self, version_id: int) -> dict[str, str | int]:
        doc_repo = DocumentRepository(self.session)
        version_repo = VersionRepository(self.session)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            storage_key = version.storage_key

        # 先删外部资源，再回写数据库状态，能明确表达“数据库记录是真理源，外部系统只是投影”。
        # 外部投影和对象清理放在事务外，避免把文件系统/外部 IO 放进数据库锁窗口。
        await self.vector_store.delete_by_version(version_id)
        await self.search_store.delete_by_version(version_id)
        await self.object_storage.delete(storage_key)

        async with self.session.begin():
            version = await version_repo.get_by_id(version_id, for_update=True)
            if version is None:
                raise NotFoundError(f"version {version_id} 不存在")
            document = await doc_repo.get_by_id(version.document_id, for_update=True)
            if document is None:
                raise NotFoundError(f"document {version.document_id} 不存在")

            version.milvus_status = ProjectionStatus.DELETED
            version.es_status = ProjectionStatus.DELETED
            version.storage_status = StorageStatus.DELETED
            if version.visibility_status == VisibilityStatus.DELETE_PENDING:
                # 只有处于待删态的版本，清理完成后才切成真正 DELETED。
                version.visibility_status = VisibilityStatus.DELETED
            version.row_version += 1

            versions = await version_repo.list_by_document(document.id)
            if versions and all(v.visibility_status == VisibilityStatus.DELETED for v in versions):
                # 只有所有版本都删完，逻辑文档本身才算真正进入 DELETED。
                document.lifecycle_status = DocumentLifecycleStatus.DELETED
                document.deleted_at = utcnow()
                document.row_version += 1

        logger.info("cleanup finished", extra={"version_id": version_id})
        return {"version_id": version_id, "status": "cleaned"}
