"""Small service composition helpers shared by API, workers, and local scripts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

try:
    from .bootstrap import (
        build_checkpoint_manager,
        build_llm,
        build_knowledge_projection_port,
        build_redis_runtime,
        build_search_reader,
        build_task_queue,
        build_vector_reader,
    )
    from .config import get_settings
    from .db import build_engine, get_session_factory
    from .application.evidence_service import EvidenceService
    from .application.global_graph_service import GlobalGraphService
    from .application.plan_service import PlanService
    from .application.progress_service import ProgressService
    from .application.run_service import RunService
    from .application.search_command_service import SearchCommandService
    from .application.session_service import SessionService
    from .application.subtask_graph_service import SubtaskGraphService
    from .application.maintenance_service import MaintenanceService
except ImportError:
    import sys
    from pathlib import Path

    demo_parent = Path(__file__).resolve().parent.parent
    if str(demo_parent) not in sys.path:
        sys.path.insert(0, str(demo_parent))
    from 最小可执行demo.bootstrap import (
        build_checkpoint_manager,
        build_llm,
        build_knowledge_projection_port,
        build_redis_runtime,
        build_search_reader,
        build_task_queue,
        build_vector_reader,
    )
    from 最小可执行demo.config import get_settings
    from 最小可执行demo.db import (
        build_engine,
        get_session_factory,
    )
    from 最小可执行demo.application.evidence_service import (
        EvidenceService,
    )
    from 最小可执行demo.application.global_graph_service import (
        GlobalGraphService,
    )
    from 最小可执行demo.application.plan_service import (
        PlanService,
    )
    from 最小可执行demo.application.progress_service import (
        ProgressService,
    )
    from 最小可执行demo.application.run_service import (
        RunService,
    )
    from 最小可执行demo.application.search_command_service import (
        SearchCommandService,
    )
    from 最小可执行demo.application.session_service import (
        SessionService,
    )
    from 最小可执行demo.application.subtask_graph_service import (
        SubtaskGraphService,
    )
    from 最小可执行demo.application.maintenance_service import (
        MaintenanceService,
    )


@dataclass(slots=True)
class RuntimeBundle:
    session_factory: async_sessionmaker
    llm: object
    redis_runtime: object
    task_queue: object
    progress_service: ProgressService
    session_service: SessionService
    evidence_service: EvidenceService
    plan_service: PlanService
    run_service: RunService
    projection_reader: object
    vector_reader: object
    search_reader: object


def build_runtime_bundle(*, use_task_engine: bool = False) -> RuntimeBundle:
    session_factory = (
        async_sessionmaker(build_engine(), expire_on_commit=False)
        if use_task_engine
        else get_session_factory()
    )
    llm = build_llm()
    redis_runtime = build_redis_runtime()
    task_queue = build_task_queue()
    progress_service = ProgressService()
    session_service = SessionService()
    evidence_service = EvidenceService(redis_runtime, llm)
    plan_service = PlanService()
    run_service = RunService(progress_service, task_queue)
    projection_reader = build_knowledge_projection_port()
    vector_reader = build_vector_reader()
    search_reader = build_search_reader()
    return RuntimeBundle(
        session_factory=session_factory,
        llm=llm,
        redis_runtime=redis_runtime,
        task_queue=task_queue,
        progress_service=progress_service,
        session_service=session_service,
        evidence_service=evidence_service,
        plan_service=plan_service,
        run_service=run_service,
        projection_reader=projection_reader,
        vector_reader=vector_reader,
        search_reader=search_reader,
    )


async def build_global_graph_service(*, use_task_engine: bool = False) -> GlobalGraphService:
    bundle = build_runtime_bundle(use_task_engine=use_task_engine)
    settings = get_settings()
    checkpointer = None
    if not settings.celery_eager:
        checkpointer = await build_checkpoint_manager().get_checkpointer()
    return GlobalGraphService(
        bundle.session_factory,
        plan_service=bundle.plan_service,
        run_service=bundle.run_service,
        evidence_service=bundle.evidence_service,
        progress_service=bundle.progress_service,
        session_service=bundle.session_service,
        checkpointer=checkpointer,
    )


def build_search_command_service(*, use_task_engine: bool = False) -> SearchCommandService:
    bundle = build_runtime_bundle(use_task_engine=use_task_engine)
    settings = get_settings()
    return SearchCommandService(
        bundle.session_factory,
        task_queue=bundle.task_queue,
        progress_service=bundle.progress_service,
        session_service=bundle.session_service,
        default_tenant_id=settings.default_tenant_id,
        default_user_id=settings.default_user_id,
    )


def build_subtask_graph_service(*, use_task_engine: bool = False) -> SubtaskGraphService:
    bundle = build_runtime_bundle(use_task_engine=use_task_engine)
    return SubtaskGraphService(
        bundle.session_factory,
        vector_reader=bundle.vector_reader,
        search_reader=bundle.search_reader,
        projection_reader=bundle.projection_reader,
        llm=bundle.llm,
        evidence_service=bundle.evidence_service,
        progress_service=bundle.progress_service,
    )


def build_maintenance_service(*, use_task_engine: bool = False) -> MaintenanceService:
    bundle = build_runtime_bundle(use_task_engine=use_task_engine)
    return MaintenanceService(
        bundle.session_factory,
        task_queue=bundle.task_queue,
        progress_service=bundle.progress_service,
        session_service=bundle.session_service,
        redis_runtime=bundle.redis_runtime,
    )
