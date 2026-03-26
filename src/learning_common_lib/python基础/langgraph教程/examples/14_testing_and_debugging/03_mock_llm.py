"""Mock LLM 调用进阶版。

目标：
    演示 FakeListChatModel / FakeMessagesListChatModel 在真实测试中的 4 类用法：
    1. tool_calls
    2. 结构化输出重试
    3. 分支序列验证
    4. interrupt/resume 恢复测试

运行命令：
    python 03_mock_llm.py
"""
from __future__ import annotations

import asyncio
import json
from typing import Literal, TypedDict

from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from pydantic import BaseModel


@tool
def search_docs(query: str) -> str:
    """搜索教程知识库。"""
    kb = {
        "langgraph": "LangGraph 用于构建有状态、可恢复的工作流。",
        "checkpoint": "Checkpoint 用于恢复运行态，不是业务真理源。",
    }
    for key, value in kb.items():
        if key in query.lower():
            return value
    return "未命中知识库"


def test_tool_call_sequence() -> None:
    """FakeMessagesListChatModel 驱动工具调用。"""
    llm = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="先查知识库",
                tool_calls=[
                    {
                        "id": "call-search-1",
                        "name": "search_docs",
                        "args": {"query": "langgraph"},
                    }
                ],
            ),
            AIMessage(content="根据工具结果，LangGraph 用于构建有状态工作流。"),
        ]
    )

    def agent(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "__end__"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode([search_docs]))
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.set_entry_point("agent")
    app = graph.compile()

    result = app.invoke({"messages": [HumanMessage(content="什么是 LangGraph？")]})
    assert "有状态工作流" in result["messages"][-1].content
    print("[PASS] test_tool_call_sequence")


class DecisionModel(BaseModel):
    decision: Literal["continue", "clarify", "fallback"]
    reason: str


def parse_structured_with_retry(llm: FakeListChatModel, *, max_attempts: int = 2) -> DecisionModel:
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        raw = llm.invoke("给出结构化决策").content
        try:
            decision = DecisionModel.model_validate_json(raw)
            print(f"  第 {attempt} 次解析成功: {decision}")
            return decision
        except Exception as exc:  # pragma: no cover - 教学用兜底
            last_error = str(exc)
            print(f"  第 {attempt} 次解析失败: {raw}")
    raise AssertionError(f"结构化输出在 {max_attempts} 次后仍失败: {last_error}")


def test_structured_output_retry() -> None:
    llm = FakeListChatModel(
        responses=[
            "NOT_JSON",
            json.dumps({"decision": "clarify", "reason": "缺少时间范围"}, ensure_ascii=False),
        ]
    )
    decision = parse_structured_with_retry(llm)
    assert decision.decision == "clarify"
    print("[PASS] test_structured_output_retry")


def test_branch_sequence() -> None:
    llm = FakeListChatModel(
        responses=[
            json.dumps({"decision": "continue", "reason": "已有足够上下文"}, ensure_ascii=False),
            json.dumps({"decision": "clarify", "reason": "需要用户补充范围"}, ensure_ascii=False),
            json.dumps({"decision": "fallback", "reason": "已达到最大重试次数"}, ensure_ascii=False),
        ]
    )
    decisions = [parse_structured_with_retry(llm, max_attempts=1).decision for _ in range(3)]
    assert decisions == ["continue", "clarify", "fallback"]
    print("[PASS] test_branch_sequence")


class ResumeState(TypedDict, total=False):
    question: str
    answer: str


async def test_resume_path() -> None:
    llm = FakeListChatModel(responses=["恢复后的最终回答：时间范围已补齐。"])

    def ask_user(state: ResumeState) -> dict:
        answer = interrupt({"question": state["question"]})
        return {"answer": str(answer)}

    def finalize(state: ResumeState) -> dict:
        result = llm.invoke(f"基于答案生成结论: {state['answer']}")
        return {"answer": result.content}

    saver = MemorySaver()
    graph = StateGraph(ResumeState)
    graph.add_node("ask", ask_user)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("ask")
    graph.add_edge("ask", "finalize")
    graph.add_edge("finalize", END)
    app = graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "mock-resume-demo"}}
    waiting = await app.ainvoke({"question": "请选择时间范围"}, config=config)
    assert waiting["question"] == "请选择时间范围"

    resumed = await app.ainvoke(Command(resume="近 30 天"), config=config)
    assert "恢复后的最终回答" in resumed["answer"]
    print("[PASS] test_resume_path")


def demo_fake_llm_basics() -> None:
    print("--- FakeListChatModel 基础行为 ---")
    llm = FakeListChatModel(responses=["第一次", "第二次", "第三次"])
    for i in range(4):
        print(f"  第 {i + 1} 次调用: {llm.invoke('hello').content}")


async def main() -> None:
    print("=== Mock LLM 进阶演示 ===\n")
    demo_fake_llm_basics()
    print()
    test_tool_call_sequence()
    test_structured_output_retry()
    test_branch_sequence()
    await test_resume_path()


if __name__ == "__main__":
    asyncio.run(main())
