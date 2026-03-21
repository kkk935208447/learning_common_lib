"""SQLAlchemy models for the deep-search demo control plane."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from ..domain.enums import (
        AnswerOrigin,
        ClaimType,
        DataPlaneFlushStatus,
        PlanStatus,
        QuestionType,
        ReliabilityTier,
        SearchTaskStatus,
        SessionRole,
        SessionStatus,
        SessionTurnType,
        SourceType,
        SubtaskRunStatus,
        SubtaskStatus,
        TaskType,
    )
    from .settings import get_settings
except ImportError:
    from 最小可执行demo.domain.enums import (
        AnswerOrigin,
        ClaimType,
        DataPlaneFlushStatus,
        PlanStatus,
        QuestionType,
        ReliabilityTier,
        SearchTaskStatus,
        SessionRole,
        SessionStatus,
        SessionTurnType,
        SourceType,
        SubtaskRunStatus,
        SubtaskStatus,
        TaskType,
    )
    from 最小可执行demo.infrastructure.settings import get_settings


TABLE_PREFIX = get_settings().table_prefix


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SearchTask(TimestampMixin, Base):
    __tablename__ = f"{TABLE_PREFIX}_search_tasks"
    __table_args__ = (
        Index(f"idx_{TABLE_PREFIX}_search_tasks_session_id", "session_id"),
        Index(f"idx_{TABLE_PREFIX}_search_tasks_status_created", "status", "created_at"),
        Index(f"idx_{TABLE_PREFIX}_search_tasks_tenant_user_status", "tenant_id", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kb_code: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[SearchTaskStatus] = mapped_column(
        Enum(SearchTaskStatus),
        nullable=False,
        default=SearchTaskStatus.PENDING,
    )
    active_plan_version: Mapped[int] = mapped_column(nullable=False, default=0)
    budget_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    control_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    final_citations_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    coverage_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    replan_count: Mapped[int] = mapped_column(nullable=False, default=0)
    clarification_count: Mapped[int] = mapped_column(nullable=False, default=0)
    preplan_clarification_used: Mapped[int] = mapped_column(nullable=False, default=0)
    postexec_clarification_used: Mapped[int] = mapped_column(nullable=False, default=0)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskPlan(Base):
    __tablename__ = f"{TABLE_PREFIX}_task_plans"
    __table_args__ = (
        UniqueConstraint("task_id", "plan_version", name=f"uq_{TABLE_PREFIX}_task_plans_task_version"),
        Index(f"idx_{TABLE_PREFIX}_task_plans_tenant_task_status", "tenant_id", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(nullable=False)
    parent_plan_version: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[PlanStatus] = mapped_column(Enum(PlanStatus), nullable=False, default=PlanStatus.ACTIVE)
    dag_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dag_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    replan_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reused_subtasks_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Subtask(TimestampMixin, Base):
    __tablename__ = f"{TABLE_PREFIX}_subtasks"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "plan_version",
            "subtask_code",
            name=f"uq_{TABLE_PREFIX}_subtasks_task_plan_code",
        ),
        Index(f"idx_{TABLE_PREFIX}_subtasks_task_plan_status", "tenant_id", "task_id", "plan_version", "status"),
        Index(f"idx_{TABLE_PREFIX}_subtasks_status_execution", "status", "current_execution_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(nullable=False)
    subtask_code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    depends_on_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    route_hints_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    acceptance_criteria_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    budget_slice_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[SubtaskStatus] = mapped_column(
        Enum(SubtaskStatus),
        nullable=False,
        default=SubtaskStatus.PENDING,
    )
    iteration: Mapped[int] = mapped_column(nullable=False, default=0)
    max_iterations: Mapped[int] = mapped_column(nullable=False, default=2)
    timeout_ms: Mapped[int] = mapped_column(nullable=False, default=30000)
    current_execution_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    final_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    key_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    result_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubtaskRun(Base):
    __tablename__ = f"{TABLE_PREFIX}_subtask_runs"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "plan_version",
            "subtask_code",
            "attempt_no",
            name=f"uq_{TABLE_PREFIX}_subtask_runs_task_plan_code_attempt",
        ),
        Index(f"idx_{TABLE_PREFIX}_subtask_runs_tenant_execution", "tenant_id", "task_id", "execution_id"),
        Index(f"idx_{TABLE_PREFIX}_subtask_runs_status_finished", "status", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(nullable=False)
    subtask_code: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[SubtaskRunStatus] = mapped_column(
        Enum(SubtaskRunStatus),
        nullable=False,
        default=SubtaskRunStatus.CLAIMED,
    )
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_token: Mapped[str | None] = mapped_column(String(96), nullable=True)
    route_used_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    usage_stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    eval_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verify_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    escalation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data_plane_ref_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data_plane_flush_status: Mapped[DataPlaneFlushStatus] = mapped_column(
        Enum(DataPlaneFlushStatus),
        nullable=False,
        default=DataPlaneFlushStatus.PENDING,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvidenceCard(Base):
    __tablename__ = f"{TABLE_PREFIX}_evidence_cards"
    __table_args__ = (
        Index(
            f"idx_{TABLE_PREFIX}_evidence_cards_task_subtask",
            "tenant_id",
            "task_id",
            "plan_version",
            "produced_by_subtask",
        ),
        Index(f"idx_{TABLE_PREFIX}_evidence_cards_task_source", "tenant_id", "task_id", "plan_version", "source_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    card_uid: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(nullable=False)
    produced_by_subtask: Mapped[str] = mapped_column(String(32), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[ClaimType] = mapped_column(Enum(ClaimType), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    source_locator_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reliability_tier: Mapped[ReliabilityTier] = mapped_column(
        Enum(ReliabilityTier),
        nullable=False,
        default=ReliabilityTier.T2,
    )
    data_freshness: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieval_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    corroborated_by_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    conflicts_with_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class TaskEvent(Base):
    __tablename__ = f"{TABLE_PREFIX}_task_events"
    __table_args__ = (
        Index(f"idx_{TABLE_PREFIX}_task_events_task_created", "task_id", "created_at"),
        Index(f"idx_{TABLE_PREFIX}_task_events_execution", "execution_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int | None] = mapped_column(nullable=True)
    subtask_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Session(TimestampMixin, Base):
    __tablename__ = f"{TABLE_PREFIX}_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mentioned_entities_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    rolling_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus),
        nullable=False,
        default=SessionStatus.ACTIVE,
    )


class SessionTurn(Base):
    __tablename__ = f"{TABLE_PREFIX}_session_turns"
    __table_args__ = (
        Index(f"idx_{TABLE_PREFIX}_session_turns_session_created", "session_id", "created_at"),
        Index(f"idx_{TABLE_PREFIX}_session_turns_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{SearchTask.__tablename__}.id", ondelete="SET NULL"),
        nullable=True,
    )
    role: Mapped[SessionRole] = mapped_column(Enum(SessionRole), nullable=False)
    turn_type: Mapped[SessionTurnType] = mapped_column(Enum(SessionTurnType), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    clarification_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question_type: Mapped[QuestionType | None] = mapped_column(Enum(QuestionType), nullable=True)
    options_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    default_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    selected_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_origin: Mapped[AnswerOrigin | None] = mapped_column(Enum(AnswerOrigin), nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
