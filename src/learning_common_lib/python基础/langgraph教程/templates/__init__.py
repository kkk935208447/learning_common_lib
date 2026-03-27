"""
LangGraph 教程 - 可复用模板模块。

目标:
    LangGraph 教程 - 可复用模板模块。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/__init__.py

运行方式:
    - 通常作为包模块导入，不建议单独运行

预期现象:
    通常不直接运行，主要用于包导入和相对导入支持

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
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
