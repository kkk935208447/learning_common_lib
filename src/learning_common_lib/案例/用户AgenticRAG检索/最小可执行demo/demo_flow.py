"""Single-process eager demo flow for the deepsearch minimum demo."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DEEPSEARCH_DEMO_CELERY_EAGER", "1")
os.environ.setdefault("MIN_RAG_CELERY_EAGER", "1")

from sqlalchemy import select

try:
    from .application.common import build_request_id, utcnow
    from .init_db import reset_tables
    from .seed_demo_kb import seed_demo_kb
    from .service_runtime import build_runtime_bundle
    from .workers.orchestrate_tasks import resume_search_async, start_search_async
    from .infrastructure.models import SearchTask
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.application.common import (
        build_request_id,
        utcnow,
    )
    from 最小可执行demo.init_db import reset_tables
    from 最小可执行demo.seed_demo_kb import seed_demo_kb
    from 最小可执行demo.service_runtime import (
        build_runtime_bundle,
    )
    from 最小可执行demo.workers.orchestrate_tasks import (
        resume_search_async,
        start_search_async,
    )
    from 最小可执行demo.infrastructure.models import (
        SearchTask,
    )


async def main() -> None:
    await reset_tables()
    await seed_demo_kb()
    runtime = build_runtime_bundle(use_task_engine=True)
    request_id = build_request_id("sess_demo_001", "请帮我整理公司近 90 天差旅报销规则的变化")

    async with runtime.session_factory() as session:
        async with session.begin():
            await runtime.session_service.ensure_session(
                session,
                session_id="sess_demo_001",
                tenant_id="demo-tenant",
                user_id="demo-user",
                initial_query="请帮我整理公司近 90 天差旅报销规则的变化",
            )
            task = SearchTask(
                request_id=request_id,
                session_id="sess_demo_001",
                tenant_id="demo-tenant",
                user_id="demo-user",
                kb_code="default",
                scope_json=None,
                original_query="请帮我整理公司近 90 天差旅报销规则的变化",
                resolved_query="请帮我整理公司近 90 天差旅报销规则的变化",
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
            await runtime.session_service.append_query_turn(
                session,
                session_id="sess_demo_001",
                task_id=task_id,
                query="请帮我整理公司近 90 天差旅报销规则的变化",
            )
            await runtime.progress_service.append_event(
                session,
                tenant_id="demo-tenant",
                task_id=task_id,
                event_type="task_submitted",
                payload_json={"request_id": request_id, "status": "PENDING", "message": "搜索任务已提交"},
            )

    print(
        "submit:",
        {
            "request_id": request_id,
            "status": "PENDING",
            "snapshot_url": f"/api/v1/search/{request_id}",
            "events_url": f"/api/v1/search/{request_id}/events",
        },
    )

    await start_search_async(task_id=task_id)
    async with runtime.session_factory() as session:
        snapshot = await runtime.progress_service.build_snapshot(session, request_id)
    print("snapshot-1:", snapshot.model_dump(mode="json"))

    if snapshot.status == "WAITING_CLARIFICATION" and snapshot.clarification_request is not None:
        async with runtime.session_factory() as session:
            async with session.begin():
                task = await session.scalar(select(SearchTask).where(SearchTask.id == task_id))
                assert task is not None
                await runtime.session_service.record_clarification_reply(
                    session,
                    session_id=task.session_id,
                    task_id=task.id,
                    selected_option_id=snapshot.clarification_request.default_option_id,
                    answer_origin="USER",
                )
                task.control_json = {
                    **(task.control_json or {}),
                    "clarification_reply_selected": snapshot.clarification_request.default_option_id,
                    "clarification_source": snapshot.clarification_request.clarification_source,
                    "waiting_reason": "NONE",
                }
                await runtime.progress_service.append_event(
                    session,
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    event_type="clarification_received",
                    payload_json={"status": "EXECUTING", "message": "demo_flow 自动提交默认澄清选项"},
                    plan_version=task.active_plan_version,
                )
        await resume_search_async(
            task_id=task_id,
            entry_action="planner" if snapshot.clarification_request.clarification_source == "PREPLAN" else "step_gate",
        )
        async with runtime.session_factory() as session:
            snapshot = await runtime.progress_service.build_snapshot(session, request_id)
        print("snapshot-2:", snapshot.model_dump(mode="json"))

    async with runtime.session_factory() as session:
        final_snapshot = await runtime.progress_service.build_snapshot(session, request_id)
    print("final:", final_snapshot.model_dump(mode="json"))


if __name__ == "__main__":
    asyncio.run(main())
