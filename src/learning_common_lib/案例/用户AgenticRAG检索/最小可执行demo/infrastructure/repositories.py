"""Repository helpers for the deep-search demo."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from ..domain.enums import PlanStatus, SearchTaskStatus, SessionTurnType, SubtaskRunStatus, SubtaskStatus
    from .models import (
        EvidenceCard,
        SearchTask,
        Session,
        SessionTurn,
        Subtask,
        SubtaskRun,
        TaskEvent,
        TaskPlan,
    )
except ImportError:
    from 最小可执行demo.domain.enums import PlanStatus, SearchTaskStatus, SessionTurnType, SubtaskRunStatus, SubtaskStatus
    from 最小可执行demo.infrastructure.models import (
        EvidenceCard,
        SearchTask,
        Session,
        SessionTurn,
        Subtask,
        SubtaskRun,
        TaskEvent,
        TaskPlan,
    )


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class SearchTaskRepository(BaseRepository):
    async def get_by_id(self, task_id: int, *, for_update: bool = False) -> SearchTask | None:
        stmt = select(SearchTask).where(SearchTask.id == task_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_by_request_id(self, request_id: str, *, for_update: bool = False) -> SearchTask | None:
        stmt = select(SearchTask).where(SearchTask.request_id == request_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_statuses(self, statuses: list[SearchTaskStatus], limit: int = 100) -> list[SearchTask]:
        stmt = select(SearchTask).where(SearchTask.status.in_(statuses)).order_by(SearchTask.id.asc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def list_waiting_clarification_before(self, deadline: datetime, limit: int = 100) -> list[SearchTask]:
        stmt = (
            select(SearchTask)
            .where(SearchTask.status == SearchTaskStatus.WAITING_CLARIFICATION)
            .where(func.json_extract(SearchTask.control_json, "$.clarification_request.expires_at").is_not(None))
            .order_by(SearchTask.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())


class TaskPlanRepository(BaseRepository):
    async def get_active_plan(self, task_id: int) -> TaskPlan | None:
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == task_id)
            .where(TaskPlan.status == PlanStatus.ACTIVE)
            .order_by(TaskPlan.plan_version.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def get_active_by_task(self, task_id: int, *, for_update: bool = False) -> TaskPlan | None:
        stmt = (
            select(TaskPlan)
            .where(TaskPlan.task_id == task_id)
            .where(TaskPlan.status == PlanStatus.ACTIVE)
            .order_by(TaskPlan.plan_version.desc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_by_version(self, task_id: int, plan_version: int, *, for_update: bool = False) -> TaskPlan | None:
        stmt = select(TaskPlan).where(TaskPlan.task_id == task_id, TaskPlan.plan_version == plan_version)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_task(self, task_id: int) -> list[TaskPlan]:
        stmt = select(TaskPlan).where(TaskPlan.task_id == task_id).order_by(TaskPlan.plan_version.asc())
        return list((await self.session.scalars(stmt)).all())


class SubtaskRepository(BaseRepository):
    async def get_by_code(
        self,
        task_id: int,
        plan_version: int,
        subtask_code: str,
        *,
        for_update: bool = False,
    ) -> Subtask | None:
        stmt = select(Subtask).where(
            Subtask.task_id == task_id,
            Subtask.plan_version == plan_version,
            Subtask.subtask_code == subtask_code,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_plan(self, task_id: int, plan_version: int) -> list[Subtask]:
        stmt = (
            select(Subtask)
            .where(Subtask.task_id == task_id, Subtask.plan_version == plan_version)
            .order_by(Subtask.priority.desc(), Subtask.subtask_code.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_by_task(self, task_id: int, plan_version: int | None = None) -> list[Subtask]:
        if plan_version is None:
            stmt = select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.priority.desc(), Subtask.subtask_code.asc())
            return list((await self.session.scalars(stmt)).all())
        return await self.list_by_plan(task_id, plan_version)

    async def list_by_statuses(
        self,
        task_id: int,
        plan_version: int,
        statuses: list[SubtaskStatus],
    ) -> list[Subtask]:
        stmt = (
            select(Subtask)
            .where(
                Subtask.task_id == task_id,
                Subtask.plan_version == plan_version,
                Subtask.status.in_(statuses),
            )
            .order_by(Subtask.priority.desc(), Subtask.subtask_code.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def count_by_statuses(
        self,
        task_id: int,
        plan_version: int,
        statuses: list[SubtaskStatus],
    ) -> int:
        stmt = select(func.count(Subtask.id)).where(
            Subtask.task_id == task_id,
            Subtask.plan_version == plan_version,
            Subtask.status.in_(statuses),
        )
        return int((await self.session.scalar(stmt)) or 0)


class SubtaskRunRepository(BaseRepository):
    async def get_by_execution_id(self, execution_id: str, *, for_update: bool = False) -> SubtaskRun | None:
        stmt = select(SubtaskRun).where(SubtaskRun.execution_id == execution_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_subtask(self, task_id: int, plan_version: int, subtask_code: str) -> list[SubtaskRun]:
        stmt = (
            select(SubtaskRun)
            .where(
                SubtaskRun.task_id == task_id,
                SubtaskRun.plan_version == plan_version,
                SubtaskRun.subtask_code == subtask_code,
            )
            .order_by(SubtaskRun.attempt_no.asc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def find_latest_by_subtask(self, task_id: int, plan_version: int, subtask_code: str) -> SubtaskRun | None:
        stmt = (
            select(SubtaskRun)
            .where(
                SubtaskRun.task_id == task_id,
                SubtaskRun.plan_version == plan_version,
                SubtaskRun.subtask_code == subtask_code,
            )
            .order_by(SubtaskRun.attempt_no.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_by_task(self, task_id: int) -> list[SubtaskRun]:
        stmt = select(SubtaskRun).where(SubtaskRun.task_id == task_id).order_by(SubtaskRun.id.asc())
        return list((await self.session.scalars(stmt)).all())

    async def list_stuck_runs(
        self,
        statuses: list[SubtaskRunStatus],
        older_than: datetime,
        limit: int = 100,
    ) -> list[SubtaskRun]:
        stmt = (
            select(SubtaskRun)
            .where(SubtaskRun.status.in_(statuses))
            .where(SubtaskRun.created_at < older_than)
            .order_by(SubtaskRun.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())


class EvidenceCardRepository(BaseRepository):
    async def get_by_card_uid(self, card_uid: str) -> EvidenceCard | None:
        stmt = select(EvidenceCard).where(EvidenceCard.card_uid == card_uid)
        return await self.session.scalar(stmt)

    async def list_by_task(
        self,
        task_id: int,
        plan_version: int | None = None,
        *,
        produced_by_subtask: str | None = None,
        limit: int = 200,
    ) -> list[EvidenceCard]:
        stmt = select(EvidenceCard).where(EvidenceCard.task_id == task_id)
        if plan_version is not None:
            stmt = stmt.where(EvidenceCard.plan_version == plan_version)
        if produced_by_subtask is not None:
            stmt = stmt.where(EvidenceCard.produced_by_subtask == produced_by_subtask)
        stmt = stmt.order_by(EvidenceCard.id.asc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())


class TaskEventRepository(BaseRepository):
    async def append_event(
        self,
        *,
        tenant_id: str,
        task_id: int,
        event_type: str,
        plan_version: int | None = None,
        subtask_code: str | None = None,
        execution_id: str | None = None,
        payload_json: dict | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            tenant_id=tenant_id,
            task_id=task_id,
            plan_version=plan_version,
            subtask_code=subtask_code,
            execution_id=execution_id,
            event_type=event_type,
            payload_json=payload_json,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def append(
        self,
        *,
        tenant_id: str,
        task_id: int,
        event_type: str,
        payload_json: dict | None = None,
        plan_version: int | None = None,
        subtask_code: str | None = None,
        execution_id: str | None = None,
    ) -> TaskEvent:
        return await self.append_event(
            tenant_id=tenant_id,
            task_id=task_id,
            event_type=event_type,
            payload_json=payload_json,
            plan_version=plan_version,
            subtask_code=subtask_code,
            execution_id=execution_id,
        )

    async def list_by_task_since(self, task_id: int, after_id: int = 0, limit: int = 200) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_after(self, task_id: int, after_id: int = 0, limit: int = 200) -> list[TaskEvent]:
        return await self.list_by_task_since(task_id, after_id, limit)

    async def get_latest_event_id(self, task_id: int) -> int:
        stmt = select(func.max(TaskEvent.id)).where(TaskEvent.task_id == task_id)
        return int((await self.session.scalar(stmt)) or 0)

    async def latest_id(self, task_id: int) -> int:
        return await self.get_latest_event_id(task_id)


class SessionRepository(BaseRepository):
    async def get_by_id(self, session_pk: int) -> Session | None:
        stmt = select(Session).where(Session.id == session_pk)
        return await self.session.scalar(stmt)

    async def get_by_session_id(self, session_id: str, *, for_update: bool = False) -> Session | None:
        stmt = select(Session).where(Session.session_id == session_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)


class SessionTurnRepository(BaseRepository):
    async def list_by_session(self, session_id: str, limit: int = 100) -> list[SessionTurn]:
        stmt = (
            select(SessionTurn)
            .where(SessionTurn.session_id == session_id)
            .order_by(SessionTurn.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_by_task(self, task_id: int, limit: int = 100) -> list[SessionTurn]:
        stmt = (
            select(SessionTurn)
            .where(SessionTurn.task_id == task_id)
            .order_by(SessionTurn.id.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def find_latest_clarification_turn(self, task_id: int) -> SessionTurn | None:
        stmt = (
            select(SessionTurn)
            .where(SessionTurn.task_id == task_id, SessionTurn.turn_type == SessionTurnType.CLARIFY_REQUEST)
            .order_by(SessionTurn.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)


async def claim_subtask(
    session: AsyncSession,
    *,
    task_id: int,
    plan_version: int,
    subtask_code: str,
    expected_row_version: int,
    execution_id: str,
) -> bool:
    result = await session.execute(
        update(Subtask)
        .where(
            Subtask.task_id == task_id,
            Subtask.plan_version == plan_version,
            Subtask.subtask_code == subtask_code,
            Subtask.status.in_((SubtaskStatus.READY, "READY")),
            Subtask.row_version == expected_row_version,
        )
        .values(
            status=SubtaskStatus.RUNNING,
            current_execution_id=execution_id,
            row_version=expected_row_version + 1,
            started_at=datetime.utcnow(),
        )
    )
    return bool(result.rowcount)
