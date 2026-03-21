"""Task event persistence, snapshot building, and SSE helpers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..domain.contracts import (
    ProgressSummary,
    TaskEventData,
    TaskEventEnvelope,
    TaskSnapshotResponse,
)
from .common import json_safe, utcnow, value_of

try:
    from ..infrastructure.models import SearchTask, SessionTurn, Subtask, TaskEvent
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask, SessionTurn, Subtask, TaskEvent


class _RuntimeCache:
    def __init__(self, redis_runtime) -> None:
        self.redis_runtime = redis_runtime
        self.settings = get_settings()

    async def load_snapshot(self, request_id: str) -> TaskSnapshotResponse | None:
        payload = await self.redis_runtime.load_json("snapshot_cache", request_id)
        if not isinstance(payload, dict):
            return None
        return TaskSnapshotResponse.model_validate(payload)

    async def store_snapshot(self, snapshot: TaskSnapshotResponse) -> None:
        await self.redis_runtime.save_json(
            "snapshot_cache",
            snapshot.request_id,
            snapshot.model_dump(mode="json"),
            ttl_seconds=self.settings.snapshot_cache_ttl_seconds,
        )

    async def delete_snapshot(self, request_id: str) -> None:
        await self.redis_runtime.delete_json("snapshot_cache", request_id)

    async def load_events_after(
        self,
        request_id: str,
        after_event_id: int,
    ) -> list[TaskEventEnvelope] | None:
        items = await self.redis_runtime.load_json_list(
            "event_cache",
            request_id,
            limit=self.settings.event_replay_max_items,
        )
        if not items:
            return None
        oldest_id = int(items[0].get("id", 0) or 0)
        if len(items) >= self.settings.event_replay_max_items and after_event_id < max(oldest_id - 1, 0):
            return None
        events = [
            TaskEventEnvelope.model_validate(item)
            for item in items
            if int(item.get("id", 0)) > after_event_id
        ]
        return events or None

    async def append_events(self, request_id: str, events: list[TaskEventEnvelope]) -> None:
        if not events:
            return
        for event in events:
            await self.redis_runtime.append_json_list(
                "event_cache",
                request_id,
                event.model_dump(mode="json"),
                ttl_seconds=self.settings.runtime_cache_ttl_seconds,
                max_items=self.settings.event_replay_max_items,
            )

    async def replace_events(self, request_id: str, events: list[TaskEventEnvelope]) -> None:
        await self.redis_runtime.delete_json_list("event_cache", request_id)
        await self.append_events(request_id, events)

    async def store_global_state(self, task_id: int, state: dict) -> None:
        await self.redis_runtime.save_json(
            "global_state",
            str(task_id),
            state,
            ttl_seconds=self.settings.runtime_cache_ttl_seconds,
        )

    async def load_global_state(self, task_id: int) -> dict | None:
        payload = await self.redis_runtime.load_json("global_state", str(task_id))
        return payload if isinstance(payload, dict) else None


class ProgressService:
    def __init__(self, redis_runtime=None) -> None:
        self.redis_runtime = redis_runtime
        self.settings = get_settings()
        self.runtime_cache = _RuntimeCache(redis_runtime) if redis_runtime is not None else None

    async def _cache_event(self, session: AsyncSession, event: TaskEvent) -> None:
        # 控制面事件以 MySQL 为真相源，避免在事务内先写 Redis 产生幽灵事件。
        return

    async def load_cached_snapshot(self, request_id: str) -> TaskSnapshotResponse | None:
        if self.runtime_cache is None:
            return None
        return await self.runtime_cache.load_snapshot(request_id)

    async def _cache_snapshot(self, snapshot: TaskSnapshotResponse) -> None:
        if self.runtime_cache is None:
            return
        await self.runtime_cache.store_snapshot(snapshot)

    async def load_cached_events_after(self, request_id: str, after_event_id: int) -> list[TaskEventEnvelope] | None:
        if self.runtime_cache is None:
            return None
        return await self.runtime_cache.load_events_after(request_id, after_event_id)

    async def append_event(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        task_id: int,
        event_type: str,
        payload_json: dict | None = None,
        plan_version: int | None = None,
        subtask_code: str | None = None,
        execution_id: str | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            tenant_id=tenant_id,
            task_id=task_id,
            plan_version=plan_version,
            subtask_code=subtask_code,
            execution_id=execution_id,
            event_type=event_type,
            payload_json=json_safe(payload_json or {}),
            created_at=utcnow(),
        )
        session.add(event)
        await session.flush()
        await self._cache_event(session, event)
        return event

    async def build_snapshot(self, session: AsyncSession, request_id: str) -> TaskSnapshotResponse:
        task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
        if task is None:
            raise ValueError(f"request_id={request_id} 不存在")

        counts_stmt = (
            select(
                func.count(Subtask.id),
                func.sum(case((Subtask.status == "COMPLETED", 1), else_=0)),
                func.sum(case((Subtask.status == "RUNNING", 1), else_=0)),
                func.sum(case((Subtask.status.in_(("PENDING", "READY")), 1), else_=0)),
            )
            .where(Subtask.task_id == task.id)
            .where(Subtask.plan_version == task.active_plan_version)
        )
        total, completed, running, waiting = (await session.execute(counts_stmt)).one()
        control_json = json_safe(task.control_json or {})
        progress = ProgressSummary(
            total_subtasks=int(total or 0),
            completed_subtasks=int(completed or 0),
            running_subtasks=int(running or 0),
            waiting_subtasks=int(waiting or 0),
            current_phase=value_of(task.status),
        )
        clarification_request = control_json.get("clarification_request") if value_of(task.status) == "WAITING_CLARIFICATION" else None
        final_citations = task.final_citations_json if isinstance(task.final_citations_json, list) else control_json.get("final_citations", [])
        snapshot = TaskSnapshotResponse(
            request_id=task.request_id,
            status=value_of(task.status),
            waiting_reason=control_json.get("waiting_reason"),
            active_plan_version=int(task.active_plan_version or 0),
            progress_summary=progress,
            final_answer=task.final_answer,
            final_citations=final_citations,
            coverage_summary=task.coverage_summary_json or control_json.get("coverage_summary"),
            clarification_request=clarification_request,
            error_code=task.last_error_code,
            error_message=task.last_error_message,
        )
        await self._cache_snapshot(snapshot)
        return snapshot

    def _event_to_envelope(self, *, request_id: str, task_status: str, event: TaskEvent) -> TaskEventEnvelope:
        payload = json_safe(event.payload_json or {})
        extra_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"request_id", "status", "message", "ts", "plan_version", "subtask_code", "execution_id"}
        }
        return TaskEventEnvelope(
            id=int(event.id),
            event=event.event_type,
            data=TaskEventData(
                request_id=request_id,
                status=payload.get("status", task_status),
                message=payload.get("message", event.event_type),
                ts=event.created_at,
                plan_version=event.plan_version,
                subtask_code=event.subtask_code,
                execution_id=event.execution_id,
                **extra_payload,
            ),
        )

    async def list_events_after(
        self,
        session: AsyncSession,
        *,
        task_id: int,
        after_event_id: int = 0,
        limit: int = 200,
    ) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .where(TaskEvent.id > after_event_id)
            .order_by(TaskEvent.id.asc())
            .limit(limit)
        )
        return list((await session.scalars(stmt)).all())

    async def stream_sse_events(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        request_id: str,
        last_event_id: int = 0,
        heartbeat_interval_s: int = 5,
    ) -> AsyncIterator[TaskEventEnvelope]:
        current_id = last_event_id
        while True:
            async with session_factory() as session:
                task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
                if task is None:
                    break
                cached_events = await self.load_cached_events_after(request_id, current_id)
                if cached_events:
                    events = cached_events
                else:
                    db_events = await self.list_events_after(session, task_id=task.id, after_event_id=current_id, limit=100)
                    events = [
                        self._event_to_envelope(
                            request_id=request_id,
                            task_status=value_of(task.status),
                            event=event,
                        )
                        for event in db_events
                    ]
                    if self.runtime_cache is not None and events:
                        await self.runtime_cache.append_events(request_id, events)
                if events:
                    for event in events:
                        current_id = int(event.id)
                        yield event
                    if value_of(task.status) in {"COMPLETED", "FAILED", "DEGRADED"}:
                        break
                else:
                    yield TaskEventEnvelope(
                        id=current_id,
                        event="heartbeat",
                        data=TaskEventData(
                            request_id=request_id,
                            ts=utcnow(),
                        ),
                    )
                    if value_of(task.status) in {"COMPLETED", "FAILED", "DEGRADED"}:
                        break
            await asyncio.sleep(heartbeat_interval_s)

    async def prime_task_cache(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        request_id: str,
        event_limit: int | None = None,
    ) -> dict[str, int]:
        if self.runtime_cache is None:
            return {"events": 0}
        async with session_factory() as session:
            snapshot = await self.build_snapshot(session, request_id)
            task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
            if task is None:
                await self.runtime_cache.delete_snapshot(request_id)
                return {"events": 0}
            db_events = await self.list_events_after(
                session,
                task_id=task.id,
                after_event_id=0,
                limit=event_limit or self.settings.event_replay_max_items,
            )
            events = [
                self._event_to_envelope(
                    request_id=request_id,
                    task_status=snapshot.status,
                    event=event,
                )
                for event in db_events
            ]
        await self.runtime_cache.store_snapshot(snapshot)
        await self.runtime_cache.replace_events(request_id, events)
        return {"events": len(events)}

    def format_sse(self, event: TaskEventEnvelope) -> str:
        return (
            f"id: {event.id}\n"
            f"event: {event.event}\n"
            f"data: {json.dumps(event.model_dump(mode='json', exclude_none=True), ensure_ascii=False)}\n\n"
        )


async def load_latest_answer_turn(session: AsyncSession, task_id: int) -> SessionTurn | None:
    stmt = (
        select(SessionTurn)
        .where(SessionTurn.task_id == task_id)
        .where(SessionTurn.turn_type == "ANSWER")
        .order_by(SessionTurn.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)
