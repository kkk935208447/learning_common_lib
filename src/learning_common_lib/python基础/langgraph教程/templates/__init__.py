"""LangGraph 教程 - 可复用模板模块。

导出所有模板的关键类和函数，方便统一导入。
"""
from __future__ import annotations

from .state_schemas import AgentState, BaseState, MessageAgentState
from .teaching_contracts import (
    ClarificationRequest,
    EscalationReport,
    ExecutionRef,
    PlanNodeSpec,
    ResumeEnvelope,
    WorkerResultEnvelope,
    WorkerTask,
)
from .safe_node import ErrorSeverity, NodeError, safe_node
from .graph_builder import GraphBuilder, build_graph
from .checkpoint_manager import CheckpointManager, get_checkpointer
from .store_manager import ResilientStore, StoreManager, get_store
from .runtime_settings import DEFAULT_RUNTIME_SETTINGS, RedisRuntimeSettings
from .multi_agent_orchestrator import Orchestrator, SupervisorAgent, WorkerAgent
from .celery_graph_bridge import (
    DispatchEnvelope,
    ResumeDecision,
    accept_or_mark_stale,
    dispatch_to_celery,
    resume_orchestrator,
)
from .fastapi_graph_app import create_graph_app, graph_lifespan

__all__ = [
    # state_schemas
    "BaseState",
    "AgentState",
    "MessageAgentState",
    # teaching_contracts
    "PlanNodeSpec",
    "WorkerTask",
    "WorkerResultEnvelope",
    "EscalationReport",
    "ClarificationRequest",
    "ExecutionRef",
    "ResumeEnvelope",
    # safe_node
    "safe_node",
    "NodeError",
    "ErrorSeverity",
    # graph_builder
    "GraphBuilder",
    "build_graph",
    # checkpoint_manager
    "CheckpointManager",
    "get_checkpointer",
    # store_manager
    "StoreManager",
    "ResilientStore",
    "get_store",
    # runtime_settings
    "RedisRuntimeSettings",
    "DEFAULT_RUNTIME_SETTINGS",
    # multi_agent_orchestrator
    "Orchestrator",
    "SupervisorAgent",
    "WorkerAgent",
    # celery_graph_bridge
    "DispatchEnvelope",
    "ResumeDecision",
    "accept_or_mark_stale",
    "dispatch_to_celery",
    "resume_orchestrator",
    # fastapi_graph_app
    "create_graph_app",
    "graph_lifespan",
]
