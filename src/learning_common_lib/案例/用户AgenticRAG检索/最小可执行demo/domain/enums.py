"""String enums used by the deepsearch demo."""

from __future__ import annotations

from enum import Enum


class SearchTaskStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_SUBTASKS = "WAITING_SUBTASKS"
    WAITING_CLARIFICATION = "WAITING_CLARIFICATION"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ABANDONED = "ABANDONED"


class TaskType(str, Enum):
    RETRIEVAL = "RETRIEVAL"
    REASONING = "REASONING"
    REFLECTION = "REFLECTION"


class DependencyType(str, Enum):
    HARD = "HARD"


class SubtaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SubtaskRunStatus(str, Enum):
    CLAIMED = "CLAIMED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    STALE_IGNORED = "STALE_IGNORED"


RunStatus = SubtaskRunStatus


class DataPlaneFlushStatus(str, Enum):
    PENDING = "PENDING"
    FLUSHING = "FLUSHING"
    FLUSHED = "FLUSHED"
    FAILED = "FAILED"


class SourceType(str, Enum):
    VECTOR_DB = "VECTOR_DB"
    ES = "ES"
    SQL_DB = "SQL_DB"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    WEB = "WEB"


class ClaimType(str, Enum):
    NUMERIC = "NUMERIC"
    CAUSAL = "CAUSAL"
    DESCRIPTIVE = "DESCRIPTIVE"
    TEMPORAL = "TEMPORAL"


class ReliabilityTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SessionRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


class SessionTurnType(str, Enum):
    QUERY = "QUERY"
    CLARIFY_REQUEST = "CLARIFY_REQUEST"
    CLARIFY_REPLY = "CLARIFY_REPLY"
    SUMMARY = "SUMMARY"
    ANSWER = "ANSWER"


class QuestionType(str, Enum):
    SINGLE_SELECT = "SINGLE_SELECT"


class AnswerOrigin(str, Enum):
    USER = "USER"
    DEFAULT_APPLIED = "DEFAULT_APPLIED"


class ClarificationSource(str, Enum):
    PREPLAN = "PREPLAN"
    STEP_GATE = "STEP_GATE"


class WaitingReason(str, Enum):
    NONE = "NONE"
    SUBTASKS = "SUBTASKS"
    CLARIFICATION = "CLARIFICATION"


class TaskEventType(str, Enum):
    TASK_SUBMITTED = "task_submitted"
    TASK_PLANNING_STARTED = "task_planning_started"
    PLAN_ACTIVATED = "plan_activated"
    SUBTASK_CLAIMED = "subtask_claimed"
    SUBTASK_DISPATCHED = "subtask_dispatched"
    SUBTASK_DISPATCH_FAILED = "subtask_dispatch_failed"
    SUBTASK_RUN_REAPED = "subtask_run_reaped"
    SUBTASK_STARTED = "subtask_started"
    SUBTASK_COMPLETED = "subtask_completed"
    SUBTASK_FAILED = "subtask_failed"
    SUBTASK_ESCALATED = "subtask_escalated"
    SUBTASK_STALE_IGNORED = "subtask_stale_ignored"
    TASK_WAITING_SUBTASKS = "task_waiting_subtasks"
    TASK_WAITING_CLARIFICATION = "task_waiting_clarification"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_RECEIVED = "clarification_received"
    CLARIFICATION_DEFAULT_APPLIED = "clarification_default_applied"
    TASK_RECOVERY_SCHEDULED = "task_recovery_scheduled"
    TASK_REPLANNED = "task_replanned"
    TASK_COMPLETED = "task_completed"
    TASK_DEGRADED = "task_degraded"
    TASK_FAILED = "task_failed"
    HEARTBEAT = "heartbeat"


class TaskName(str, Enum):
    START_SEARCH = "deepsearch.start_search"
    RESUME_SEARCH = "deepsearch.resume_search"
    EXECUTE_SUBTASK = "deepsearch.execute_subtask"
    FLUSH_DATA_PLANE = "deepsearch.flush_data_plane"
    REAP_STUCK_RUNS = "deepsearch.reap_stuck_runs"
    APPLY_CLARIFY_DEFAULTS = "deepsearch.apply_clarify_defaults"
    REBUILD_RUNTIME_CACHE = "deepsearch.rebuild_runtime_cache"
    RECOVER_ORCHESTRATION_GAPS = "deepsearch.recover_orchestration_gaps"


class QueueName(str, Enum):
    ORCHESTRATE = "orchestrate_jobs"
    SUBTASK = "subtask_jobs"
    PERSIST = "persist_jobs"
    MAINTENANCE = "maintenance_jobs"
