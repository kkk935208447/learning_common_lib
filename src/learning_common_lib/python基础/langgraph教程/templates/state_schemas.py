"""
可复用状态 schema 基类，为 LangGraph 图提供标准化的状态定义。

目标:
    可复用状态 schema 基类，为 LangGraph 图提供标准化的状态定义。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: templates/state_schemas.py

运行方式:
    - 通常作为模块导入，不建议单独运行

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# ---------------------------------------------------------------------------
# 基础状态
# ---------------------------------------------------------------------------

class BaseState(TypedDict, total=False):
    """基础状态 schema，包含通用字段。

    所有字段均为可选，子类可按需继承并扩展。
    """

    error: str | None
    metadata: dict
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Agent 状态
# ---------------------------------------------------------------------------

class AgentState(BaseState, total=False):
    """Agent 状态，包含迭代控制字段。

    - iteration: 当前迭代次数
    - max_iterations: 最大迭代次数（防止无限循环）
    - next_action: 路由决策字段
    """

    iteration: int
    max_iterations: int
    next_action: str


# ---------------------------------------------------------------------------
# 消息型 Agent 状态
# ---------------------------------------------------------------------------

class MessageAgentState(AgentState):
    """消息型 Agent 状态，使用 add_messages reducer 自动合并消息列表。"""

    messages: Annotated[list[AnyMessage], add_messages]
