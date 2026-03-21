"""Task event persistence, snapshot building, and SSE helpers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


class ProgressService:
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
        return TaskSnapshotResponse(
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
                events = await self.list_events_after(session, task_id=task.id, after_event_id=current_id, limit=100)
                if events:
                    for event in events:
                        payload = json_safe(event.payload_json or {})
                        current_id = int(event.id)
                        yield TaskEventEnvelope(
                            id=int(event.id),
                            event=event.event_type,
                            data=TaskEventData(
                                request_id=request_id,
                                status=payload.get("status", value_of(task.status)),
                                message=payload.get("message", event.event_type),
                                ts=event.created_at,
                                plan_version=event.plan_version,
                                subtask_code=event.subtask_code,
                                execution_id=event.execution_id,
                            ),
                        )
                    if value_of(task.status) in {"COMPLETED", "FAILED", "DEGRADED"}:
                        break
                else:
                    yield TaskEventEnvelope(
                        id=current_id,
                        event="heartbeat",
                        data=TaskEventData(
                            request_id=request_id,
                            status=value_of(task.status),
                            message="heartbeat",
                            ts=utcnow(),
                            plan_version=task.active_plan_version,
                        ),
                    )
                    if value_of(task.status) in {"COMPLETED", "FAILED", "DEGRADED"}:
                        break
            await asyncio.sleep(heartbeat_interval_s)

    def format_sse(self, event: TaskEventEnvelope) -> str:
        return (
            f"id: {event.id}\n"
            f"event: {event.event}\n"
            f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
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
