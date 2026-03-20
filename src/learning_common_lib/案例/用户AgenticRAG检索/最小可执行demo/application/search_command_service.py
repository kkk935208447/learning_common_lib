"""HTTP-facing command service for submit/query/clarification flows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.contracts import SearchAcceptedResponse, SearchSubmitRequest, TaskSnapshotResponse
from ..domain.enums import QueueName, TaskName
from ..errors import ConflictError, NotFoundError, ValidationError
from .common import build_request_id, json_safe, utcnow, value_of
from .progress_service import ProgressService
from .session_service import SessionService

try:
    from ..infrastructure.models import SearchTask
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask


class SearchCommandService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        task_queue,
        progress_service: ProgressService,
        session_service: SessionService,
        default_tenant_id: str,
        default_user_id: str,
    ) -> None:
        self.session_factory = session_factory
        self.task_queue = task_queue
        self.progress_service = progress_service
        self.session_service = session_service
        self.default_tenant_id = default_tenant_id
        self.default_user_id = default_user_id

    async def submit_search(self, request: SearchSubmitRequest) -> SearchAcceptedResponse:
        if not request.query.strip():
            raise ValidationError("query 不能为空")

        request_id = build_request_id(request.session_id, request.query)
        async with self.session_factory() as session:
            async with session.begin():
                await self.session_service.ensure_session(
                    session,
                    session_id=request.session_id,
                    tenant_id=self.default_tenant_id,
                    user_id=self.default_user_id,
                    initial_query=request.query,
                )
                task = SearchTask(
                    request_id=request_id,
                    session_id=request.session_id,
                    tenant_id=self.default_tenant_id,
                    user_id=self.default_user_id,
                    kb_code=request.kb_code or "default",
                    scope_json=request.scope_json,
                    original_query=request.query.strip(),
                    resolved_query=request.query.strip(),
                    task_profile_json={},
                    status="PENDING",
                    active_plan_version=0,
                    budget_json={},
                    control_json={"waiting_reason": "NONE"},
                    replan_count=0,
                    clarification_count=0,
                    preplan_clarification_used=0,
                    postexec_clarification_used=0,
                    row_version=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                session.add(task)
                await session.flush()
                await self.session_service.append_query_turn(
                    session,
                    session_id=request.session_id,
                    task_id=task.id,
                    query=request.query.strip(),
                )
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="task_submitted",
                    payload_json={"request_id": request_id, "status": "PENDING", "message": "搜索任务已提交"},
                )
            self.task_queue.dispatch(
                task_name=TaskName.START_SEARCH.value,
                payload={"task_id": task.id},
                queue_name=QueueName.ORCHESTRATE.value,
            )

        return SearchAcceptedResponse(
            request_id=request_id,
            status="PENDING",
            snapshot_url=f"/api/v1/search/{request_id}",
            events_url=f"/api/v1/search/{request_id}/events",
        )

    async def get_snapshot(self, request_id: str) -> TaskSnapshotResponse:
        async with self.session_factory() as session:
            try:
                return await self.progress_service.build_snapshot(session, request_id)
            except ValueError as exc:
                raise NotFoundError(str(exc)) from exc

    async def submit_clarification(self, request_id: str, selected_option_id: str) -> TaskSnapshotResponse:
        async with self.session_factory() as session:
            async with session.begin():
                task = await session.scalar(select(SearchTask).where(SearchTask.request_id == request_id))
                if task is None:
                    raise NotFoundError(f"request_id={request_id} 不存在")
                if value_of(task.status) != "WAITING_CLARIFICATION":
                    raise ConflictError("任务当前不处于 WAITING_CLARIFICATION")

                control_json = json_safe(task.control_json or {})
                if control_json.get("clarification_reply_selected"):
                    return await self.progress_service.build_snapshot(session, request_id)

                latest_request = await self.session_service.validate_clarification_answer(
                    session,
                    task_id=task.id,
                    selected_option_id=selected_option_id,
                )
                await self.session_service.record_clarification_reply(
                    session,
                    session_id=task.session_id,
                    task_id=task.id,
                    selected_option_id=selected_option_id,
                    answer_origin="USER",
                )
                clarification_source = latest_request.clarification_source or control_json.get("clarification_source") or "PREPLAN"
                task.status = "EXECUTING"
                task.control_json = {
                    **control_json,
                    "clarification_reply_selected": selected_option_id,
                    "clarification_source": clarification_source,
                    "waiting_reason": "NONE",
                }
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="clarification_received",
                    payload_json={"status": "EXECUTING", "message": f"收到澄清选项 {selected_option_id}"},
                    plan_version=task.active_plan_version,
                )
            self.task_queue.dispatch(
                task_name=TaskName.RESUME_SEARCH.value,
                payload={"task_id": task.id, "entry_action": "planner" if clarification_source == "PREPLAN" else "step_gate"},
                queue_name=QueueName.ORCHESTRATE.value,
            )
        return await self.get_snapshot(request_id)
