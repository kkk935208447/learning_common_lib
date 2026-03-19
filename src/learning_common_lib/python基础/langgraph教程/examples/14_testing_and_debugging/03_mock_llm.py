"""Mock LLM 调用

目标：
    演示使用 FakeListChatModel 进行确定性测试，
    无需 API key 即可验证图的逻辑正确性。

关键 API：
    - FakeListChatModel —— 按顺序返回预设回复
    - FakeMessagesListChatModel —— 返回预设 Message 对象

运行命令：
    python 03_mock_llm.py

预期现象：
    使用 mock LLM 的图产生确定性输出，每次运行结果一致。

生产提醒：
    - FakeListChatModel 按顺序循环返回 responses 列表中的内容
    - 测试时应覆盖 LLM 返回不同内容的场景（正常/异常/边界）
    - Mock 测试验证逻辑正确性，上线前仍需真实 LLM 的冒烟测试
"""
from __future__ import annotations

from typing import TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, MessagesState, StateGraph


# ══════════════════════════════════════════════════════════
# 演示 1：FakeListChatModel 基础用法
# ══════════════════════════════════════════════════════════

def demo_fake_llm_basics() -> None:
    """FakeListChatModel 按顺序返回预设回复"""
    print("--- FakeListChatModel 基础用法 ---\n")

    llm = FakeListChatModel(responses=[
        "第一次调用的回复",
        "第二次调用的回复",
        "第三次调用的回复",
    ])

    # 每次调用按顺序返回，循环使用
    for i in range(4):
        result = llm.invoke("任意输入")
        print(f"  第 {i + 1} 次调用: {result.content}")


# ══════════════════════════════════════════════════════════
# 演示 2：在图中使用 Mock LLM
# ══════════════════════════════════════════════════════════

class AnalysisState(TypedDict):
    text: str
    sentiment: str
    summary: str


def build_analysis_graph(sentiment_response: str, summary_response: str):
    """构建分析图，注入 mock LLM 响应"""

    def sentiment_node(state: AnalysisState) -> dict:
        # 每个节点使用独立的 mock LLM 实例
        llm = FakeListChatModel(responses=[sentiment_response])
        result = llm.invoke(f"分析情感: {state['text']}")
        return {"sentiment": result.content}

    def summary_node(state: AnalysisState) -> dict:
        llm = FakeListChatModel(responses=[summary_response])
        result = llm.invoke(f"生成摘要: {state['text']}")
        return {"summary": result.content}

    graph = StateGraph(AnalysisState)
    graph.add_node("sentiment", sentiment_node)
    graph.add_node("summary", summary_node)
    graph.set_entry_point("sentiment")
    graph.add_edge("sentiment", "summary")
    graph.add_edge("summary", END)
    return graph.compile()


def test_positive_sentiment() -> None:
    """测试正面情感分析"""
    app = build_analysis_graph(
        sentiment_response="positive",
        summary_response="这是一段积极正面的评价。",
    )
    result = app.invoke({"text": "这个产品太棒了！", "sentiment": "", "summary": ""})
    assert result["sentiment"] == "positive"
    assert "积极" in result["summary"]
    print("  [PASS] test_positive_sentiment")


def test_negative_sentiment() -> None:
    """测试负面情感分析"""
    app = build_analysis_graph(
        sentiment_response="negative",
        summary_response="这是一段负面的反馈。",
    )
    result = app.invoke({"text": "质量太差了", "sentiment": "", "summary": ""})
    assert result["sentiment"] == "negative"
    print("  [PASS] test_negative_sentiment")


# ══════════════════════════════════════════════════════════
# 演示 3：Mock 多轮对话
# ══════════════════════════════════════════════════════════

def build_chat_graph(responses: list[str]):
    """构建多轮对话图"""
    llm = FakeListChatModel(responses=responses)

    def chat_node(state: MessagesState) -> dict:
        result = llm.invoke(state["messages"])
        return {"messages": [result]}

    graph = StateGraph(MessagesState)
    graph.add_node("chat", chat_node)
    graph.set_entry_point("chat")
    graph.add_edge("chat", END)
    return graph.compile()


def test_multi_turn_chat() -> None:
    """测试多轮对话的确定性"""
    app = build_chat_graph(responses=[
        "你好！我是 AI 助手。",
        "LangGraph 是一个构建有状态 AI 应用的框架。",
    ])

    # 第一轮
    r1 = app.invoke({"messages": [HumanMessage(content="你好")]})
    assert "AI 助手" in r1["messages"][-1].content

    # 第二轮（新的 invoke，LLM 返回第二个预设回复）
    r2 = app.invoke({"messages": [HumanMessage(content="什么是 LangGraph？")]})
    assert "框架" in r2["messages"][-1].content

    print("  [PASS] test_multi_turn_chat")


if __name__ == "__main__":
    print("=== Mock LLM 演示 ===\n")

    demo_fake_llm_basics()

    print("\n=== Mock LLM 测试 ===\n")
    tests = [test_positive_sentiment, test_negative_sentiment, test_multi_turn_chat]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")

    print(f"\n结果: {passed}/{len(tests)} 通过")
