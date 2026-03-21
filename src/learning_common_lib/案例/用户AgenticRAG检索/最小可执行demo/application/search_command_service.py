"""HTTP-facing command service for submit/query/clarification flows."""

from __future__ import annotations

from typing import Awaitable, Callable

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
    from ..ports.task_queue_port import TaskDispatchError
except ImportError:
    from 最小可执行demo.infrastructure.models import SearchTask
    from 最小可执行demo.ports.task_queue_port import TaskDispatchError


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

    async def _dispatch_or_run_locally(
        self,
        *,
        task_name: str,
        payload: dict[str, object],
        queue_name: str,
        local_runner: Callable[[], Awaitable[dict[str, object]]],
    ) -> None:
        try:
            self.task_queue.dispatch(
                task_name=task_name,
                payload=payload,
                queue_name=queue_name,
            )
        except TaskDispatchError:
            await local_runner()

    async def submit_search(self, request: SearchSubmitRequest) -> SearchAcceptedResponse:
        if not request.query.strip():
            raise ValidationError("query 不能为空")
        if request.kb_code and request.kb_code != "default":
            raise ValidationError("当前最小 demo 仅支持 kb_code=default")

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
                task_id = task.id
                await self.session_service.append_query_turn(
                    session,
                    session_id=request.session_id,
                    task_id=task_id,
                    query=request.query.strip(),
                )
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task_id,
                    event_type="task_submitted",
                    payload_json={"request_id": request_id, "status": "PENDING", "message": "搜索任务已提交"},
                )

        try:
            from ..workers.orchestrate_tasks import start_search_async
        except ImportError:
            from 最小可执行demo.workers.orchestrate_tasks import start_search_async

        await self._dispatch_or_run_locally(
            task_name=TaskName.START_SEARCH.value,
            payload={"task_id": task_id},
            queue_name=QueueName.ORCHESTRATE.value,
            local_runner=lambda: start_search_async(task_id=task_id, drain_eager=False),
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
                task = await session.scalar(
                    select(SearchTask).where(SearchTask.request_id == request_id).with_for_update()
                )
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
                task_id = task.id
                await self.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task_id,
                    event_type="clarification_received",
                    payload_json={"status": "EXECUTING", "message": f"收到澄清选项 {selected_option_id}"},
                    plan_version=task.active_plan_version,
                )

        entry_action = "planner" if clarification_source == "PREPLAN" else "step_gate"
        try:
            from ..workers.orchestrate_tasks import resume_search_async
        except ImportError:
            from 最小可执行demo.workers.orchestrate_tasks import resume_search_async

        await self._dispatch_or_run_locally(
            task_name=TaskName.RESUME_SEARCH.value,
            payload={"task_id": task_id, "entry_action": entry_action},
            queue_name=QueueName.ORCHESTRATE.value,
            local_runner=lambda: resume_search_async(
                task_id=task_id,
                entry_action=entry_action,
                drain_eager=False,
            ),
        )
        return await self.get_snapshot(request_id)
