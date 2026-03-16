from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..bootstrap import build_lock_port, build_task_queue
    from ..config import get_settings
    from ..db import session_scope, task_session_scope
    from ..enums import PublishStatus, TaskName
    from ..models import OutboxEvent
    from ..repositories import OutboxRepository
    from .common import should_dispatch_event, utcnow
except ImportError:
    from bootstrap import build_lock_port, build_task_queue
    from config import get_settings
    from db import session_scope, task_session_scope
    from enums import PublishStatus, TaskName
    from models import OutboxEvent
    from repositories import OutboxRepository
    from services.common import should_dispatch_event, utcnow

logger = logging.getLogger(__name__)


class OutboxDispatcherService:
    def __init__(self, session: AsyncSession, task_queue) -> None:
        self.session = session
        self.task_queue = task_queue

    async def dispatch_pending(self, limit: int = 100) -> int:
        repo = OutboxRepository(self.session)
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
            if should_dispatch_event(
                publish_status=event.publish_status,
                next_retry_at=event.next_retry_at,
            )
        ]
        await self.session.rollback()

        sent = 0
        for event in event_snapshots:
            try:
                task_id = await self._dispatch_one(event)
                sent += 1
                await self._mark_event_sent(event_id=event["event_id"], task_id=task_id)
            except Exception as exc:
                logger.warning(
                    "dispatch pending task failed: %s",
                    exc,
                    extra={
                        "event_id": event["event_id"],
                        "task_name": event["task_name"],
                        "payload_json": event["payload_json"],
                    },
                )
                await self._mark_event_failed(event_id=event["event_id"])
        return sent

    async def cleanup_sent_history(self) -> int:
        repo = OutboxRepository(self.session)
        async with self.session.begin():
            return await repo.cleanup_sent_older_than(get_settings().outbox_cleanup_days)

    async def list_pending_events(self, limit: int = 100) -> list[OutboxEvent]:
        repo = OutboxRepository(self.session)
        return await repo.list_pending(limit)

    async def pending_count(self) -> int:
        repo = OutboxRepository(self.session)
        return await repo.count_pending()

    async def _dispatch_one(self, event: dict[str, Any]) -> str | None:
        if get_settings().celery_eager:
            await execute_local_task(
                task_name=event["task_name"],
                payload=event["payload_json"],
            )
            return None
        return await asyncio.to_thread(
            self.task_queue.dispatch,
            task_name=event["task_name"],
            payload=event["payload_json"],
            queue_name=event["queue_name"],
        )

    async def _mark_event_sent(self, *, event_id: int, task_id: str | None) -> None:
        async with self.session.begin():
            event = await self.session.get(OutboxEvent, event_id, with_for_update=True)
            if event is None:
                return
            event.publish_status = PublishStatus.SENT
            event.published_at = utcnow()
            event.next_retry_at = None
            if task_id is not None:
                payload = dict(event.payload_json)
                payload["celery_task_id"] = task_id
                event.payload_json = payload

    async def _mark_event_failed(self, *, event_id: int) -> None:
        async with self.session.begin():
            event = await self.session.get(OutboxEvent, event_id, with_for_update=True)
            if event is None:
                return
            event.publish_status = PublishStatus.FAILED
            event.next_retry_at = utcnow() + timedelta(seconds=get_settings().task_retry_base_seconds)


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
        async with task_session_scope() as session:
            dispatcher = OutboxDispatcherService(session, build_task_queue())
            count = await dispatcher.dispatch_pending(limit=limit)
            logger.info("best effort dispatch outbox finished", extra={"sent": count})
    except Exception as exc:
        logger.warning("best effort dispatch outbox failed: %s", exc)
    finally:
        if lock is not None and token is not None:
            await asyncio.to_thread(lock.release, "rag:outbox:dispatcher", token)


async def execute_local_task(task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with session_scope() as session:
        if task_name == TaskName.PARSE_VERSION.value:
            try:
                from ..bootstrap import build_object_storage
                from .parse_pipeline import ParsePipelineService
            except ImportError:
                from bootstrap import build_object_storage
                from services.parse_pipeline import ParsePipelineService

            service = ParsePipelineService(session, build_object_storage())
            return await service.run(payload["version_id"])
        if task_name == TaskName.INDEX_VERSION.value:
            try:
                from ..bootstrap import build_embedding_provider, build_search_store, build_vector_store
                from .index_pipeline import IndexPipelineService
            except ImportError:
                from bootstrap import build_embedding_provider, build_search_store, build_vector_store
                from services.index_pipeline import IndexPipelineService

            service = IndexPipelineService(
                session,
                build_vector_store(),
                build_search_store(),
                build_embedding_provider(),
            )
            return await service.run(payload["version_id"])
        if task_name == TaskName.CLEAN_VERSION.value:
            try:
                from ..bootstrap import build_object_storage, build_search_store, build_vector_store
                from .cleanup import CleanupService
            except ImportError:
                from bootstrap import build_object_storage, build_search_store, build_vector_store
                from services.cleanup import CleanupService

            service = CleanupService(
                session,
                build_object_storage(),
                build_vector_store(),
                build_search_store(),
            )
            return await service.run(payload["version_id"])
        if task_name == TaskName.JANITOR_SCAN.value:
            try:
                from ..bootstrap import build_search_store, build_vector_store
                from .janitor import JanitorService
            except ImportError:
                from bootstrap import build_search_store, build_vector_store
                from services.janitor import JanitorService

            service = JanitorService(session, build_vector_store(), build_search_store())
            return await service.run_once()
        raise ValueError(f"未知 task_name: {task_name}")
