"""Celery task implementations that adapt service methods to worker processes."""

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
    from .celery_runtime import celery_app
    from .config import get_settings
    from .db import task_session_scope
    from .errors import DemoError, RetryableTaskError
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
    from celery_runtime import celery_app
    from config import get_settings
    from db import task_session_scope
    from errors import DemoError, RetryableTaskError
    from enums import TaskName
    from services import CleanupService, IndexPipelineService, JanitorService, OutboxDispatcherService, ParsePipelineService
    from task_queue import CeleryTaskQueueAdapter

# tasks.py 只负责把 Celery 协议层接到服务层，不在这里重写业务逻辑。
def _retry_countdown(retries: int) -> int:
    settings = get_settings()
    # 指数退避用最简单的 2^n 形式，足够演示 Celery 重试节奏。
    return settings.task_retry_base_seconds * (2 ** retries)


def _should_retry(exc: Exception) -> bool:
    # 未知异常默认按“可能是临时故障”处理，教学上更能体现“宁可重复，不要静默丢任务”。
    return isinstance(exc, RetryableTaskError) or not isinstance(exc, DemoError)


def _run_locked(lock_key: str | None, runner) -> dict[str, Any]:
    if lock_key is None:
        # 某些任务允许并发执行时，直接运行即可，不额外申请排他锁。
        return asyncio.run(runner())
    settings = get_settings()
    lock = build_lock_port()
    token = lock.try_lock(lock_key, settings.lock_ttl_seconds)
    if token is None:
        return {"status": "skipped", "reason": "lock_not_acquired", "lock_key": lock_key}
    try:
        return asyncio.run(runner())
    finally:
        lock.release(lock_key, token)


def _execute_task(self: Any, *, lock_key: str | None, runner) -> dict[str, Any]:
    settings = get_settings()
    try:
        # Parser / Index 之类的任务允许重复投递，但同一版本同一时刻只跑一个实例。
        return _run_locked(lock_key, runner)
    except Exception as exc:
        if _should_retry(exc) and self.request.retries < settings.task_max_retries:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        raise


@celery_app.task(bind=True, name=TaskName.DISPATCH_OUTBOX.value)
def dispatch_outbox(self: Any) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        lock = build_lock_port()
        # Dispatcher 额外加一个 leader lock，避免 Beat 和 API 手动触发同时扫同一批 Outbox。
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
    async def _run() -> dict[str, Any]:
        # Outbox 历史清理和主派发解耦，避免大批量删除影响实时投递。
        async with task_session_scope() as session:
            dispatcher = OutboxDispatcherService(session, CeleryTaskQueueAdapter())
            deleted = await dispatcher.cleanup_sent_history()
            return {"deleted": deleted}

    return asyncio.run(_run())


@celery_app.task(bind=True, name=TaskName.PARSE_VERSION.value)
def parse_version(self: Any, version_id: int) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        # task 层只装配依赖，ParsePipelineService 才是实际的解析状态机。
        async with task_session_scope() as session:
            service = ParsePipelineService(session, build_object_storage())
            return await service.run(version_id)

    return _execute_task(self, lock_key=f"rag:parse:version:{version_id}", runner=_run)


@celery_app.task(bind=True, name=TaskName.INDEX_VERSION.value)
def index_version(self: Any, version_id: int) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        # Index 任务在这里集中装配 embedding/vector/search 三类依赖。
        async with task_session_scope() as session:
            service = IndexPipelineService(
                session,
                build_vector_store(),
                build_search_store(),
                build_embedding_provider(),
            )
            return await service.run(version_id)

    return _execute_task(self, lock_key=f"rag:index:version:{version_id}", runner=_run)


@celery_app.task(bind=True, name=TaskName.CLEAN_VERSION.value)
def clean_version(self: Any, version_id: int) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        # Cleaner 不加版本级锁，原因是 dedupe_key 已经把同类清理请求压到很低。
        async with task_session_scope() as session:
            service = CleanupService(
                session,
                build_object_storage(),
                build_vector_store(),
                build_search_store(),
            )
            return await service.run(version_id)

    return _execute_task(self, lock_key=None, runner=_run)


@celery_app.task(bind=True, name=TaskName.JANITOR_SCAN.value)
def janitor_scan(self: Any) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        async with task_session_scope() as session:
            service = JanitorService(session, build_vector_store(), build_search_store())
            return await service.run_once()

    # Janitor 也是单领导者任务，避免多 worker 周期性重复扫描同一批 active 版本。
    return _run_locked("rag:janitor:leader", _run)
