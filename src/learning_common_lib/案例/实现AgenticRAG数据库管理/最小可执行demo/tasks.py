from __future__ import annotations

import asyncio
from typing import Any

try:
    from .bootstrap import (
        build_embedding_provider,
        build_lock_port,
        build_object_storage,
        build_search_store,
        build_vector_store,
    )
    from .celery_app import celery_app
    from .config import get_settings
    from .db import task_session_scope
    from .enums import TaskName
    from .services import CleanupService, IndexPipelineService, JanitorService, OutboxDispatcherService, ParsePipelineService
    from .task_queue import CeleryTaskQueueAdapter
except ImportError:
    from bootstrap import (
        build_embedding_provider,
        build_lock_port,
        build_object_storage,
        build_search_store,
        build_vector_store,
    )
    from celery_app import celery_app
    from config import get_settings
    from db import task_session_scope
    from enums import TaskName
    from services import CleanupService, IndexPipelineService, JanitorService, OutboxDispatcherService, ParsePipelineService
    from task_queue import CeleryTaskQueueAdapter

_TASKS_REGISTERED = False


def ensure_tasks_registered() -> None:
    global _TASKS_REGISTERED
    _TASKS_REGISTERED = True


def _retry_countdown(retries: int) -> int:
    settings = get_settings()
    return settings.task_retry_base_seconds * (2 ** retries)


def _run_with_lock(lock_key: str | None, runner) -> dict[str, Any]:
    if lock_key is None:
        return runner()
    settings = get_settings()
    lock = build_lock_port()
    token = lock.try_lock(lock_key, settings.lock_ttl_seconds)
    if token is None:
        return {"status": "skipped", "reason": "lock_not_acquired", "lock_key": lock_key}
    try:
        return runner()
    finally:
        lock.release(lock_key, token)


@celery_app.task(bind=True, name=TaskName.DISPATCH_OUTBOX.value)
def dispatch_outbox(self: Any) -> dict[str, Any]:
    ensure_tasks_registered()

    async def _run() -> dict[str, Any]:
        lock = build_lock_port()
        token = await asyncio.to_thread(lock.try_lock, "rag:outbox:dispatcher", get_settings().lock_ttl_seconds)
        if token is None:
            return {"sent": 0, "reason": "lock_not_acquired"}
        try:
            async with task_session_scope() as session:
                dispatcher = OutboxDispatcherService(session, CeleryTaskQueueAdapter())
                count = await dispatcher.dispatch_pending(limit=100)
                return {"sent": count}
        finally:
            await asyncio.to_thread(lock.release, "rag:outbox:dispatcher", token)

    return asyncio.run(_run())


@celery_app.task(bind=True, name=TaskName.CLEAN_OUTBOX.value)
def clean_outbox(self: Any) -> dict[str, Any]:
    ensure_tasks_registered()

    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            dispatcher = OutboxDispatcherService(session, CeleryTaskQueueAdapter())
            deleted = await dispatcher.cleanup_sent_history()
            return {"deleted": deleted}

    return asyncio.run(_run())


@celery_app.task(bind=True, name=TaskName.PARSE_VERSION.value)
def parse_version(self: Any, version_id: int) -> dict[str, Any]:
    ensure_tasks_registered()
    settings = get_settings()

    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            service = ParsePipelineService(session, build_object_storage())
            return await service.run(version_id)

    try:
        return _run_with_lock(
            f"rag:parse:version:{version_id}",
            lambda: asyncio.run(_run()),
        )
    except Exception as exc:
        if self.request.retries < settings.task_max_retries:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        raise


@celery_app.task(bind=True, name=TaskName.INDEX_VERSION.value)
def index_version(self: Any, version_id: int) -> dict[str, Any]:
    ensure_tasks_registered()
    settings = get_settings()

    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            service = IndexPipelineService(
                session,
                build_vector_store(),
                build_search_store(),
                build_embedding_provider(),
            )
            return await service.run(version_id)

    try:
        return _run_with_lock(
            f"rag:index:version:{version_id}",
            lambda: asyncio.run(_run()),
        )
    except Exception as exc:
        if self.request.retries < settings.task_max_retries:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        raise


@celery_app.task(bind=True, name=TaskName.CLEAN_VERSION.value)
def clean_version(self: Any, version_id: int) -> dict[str, Any]:
    ensure_tasks_registered()
    settings = get_settings()

    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            service = CleanupService(
                session,
                build_object_storage(),
                build_vector_store(),
                build_search_store(),
            )
            return await service.run(version_id)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        if self.request.retries < settings.task_max_retries:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        raise


@celery_app.task(bind=True, name=TaskName.JANITOR_SCAN.value)
def janitor_scan(self: Any) -> dict[str, Any]:
    ensure_tasks_registered()

    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            service = JanitorService(session, build_vector_store(), build_search_store())
            return await service.run_once()

    return _run_with_lock("rag:janitor:leader", lambda: asyncio.run(_run()))
