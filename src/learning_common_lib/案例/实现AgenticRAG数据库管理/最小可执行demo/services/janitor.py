from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..enums import AggregateType, OutboxEventType, QueueName, TaskName
    from ..repositories import ChunkRepository, VersionRepository
    from ..search_store import BaseSearchStore
    from ..vector_store import BaseVectorStore
    from .common import build_outbox_event
    from .outbox_dispatcher import best_effort_dispatch_outbox
except ImportError:
    from enums import AggregateType, OutboxEventType, QueueName, TaskName
    from repositories import ChunkRepository, VersionRepository
    from search_store import BaseSearchStore
    from vector_store import BaseVectorStore
    from services.common import build_outbox_event
    from services.outbox_dispatcher import best_effort_dispatch_outbox

logger = logging.getLogger(__name__)


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

    async def run_once(self, limit: int | None = None) -> dict[str, int]:
        try:
            from ..config import get_settings
        except ImportError:
            from config import get_settings

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
            logger.info("janitor requested rebuild", extra={"versions": versions_to_rebuild})
            await best_effort_dispatch_outbox()
        return {"scanned": len(active_versions), "rebuild_requested": rebuild_count}
