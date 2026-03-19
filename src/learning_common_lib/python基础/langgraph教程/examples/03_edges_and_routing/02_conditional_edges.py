"""二路/多路条件边。

目标：掌握 add_conditional_edges 实现动态路由
关键 API：add_conditional_edges, 路由函数, 路由映射 dict
运行命令：python 02_conditional_edges.py
预期现象：根据状态中的 sentiment 字段动态选择不同处理路径
生产提醒：路由函数必须返回映射 dict 中的 key；建议设置默认路由防止遗漏
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    text: str
    sentiment: str
    result: str
    log: Annotated[list[str], operator.add]


# ---------- 路由函数 ----------
def sentiment_router(state: State) -> str:
    """路由函数：根据 sentiment 决定走哪条边。

    路由函数签名：接收 State，返回字符串（映射 dict 的 key）。
    """
    sentiment = state.get("sentiment", "neutral")
    if sentiment == "positive":
        return "positive"
    elif sentiment == "negative":
        return "negative"
    else:
        return "neutral"  # 默认路由


# ---------- 节点函数 ----------
def analyze(state: State) -> dict:
    """分析节点：模拟情感分析。"""
    text = state["text"]
    # 简单规则模拟
    if "好" in text or "棒" in text:
        sentiment = "positive"
    elif "差" in text or "糟" in text:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    print(f"[analyze] text='{text}' -> sentiment='{sentiment}'")
    return {"sentiment": sentiment, "log": [f"分析结果: {sentiment}"]}


def handle_positive(state: State) -> dict:
    print("[positive] 正面情感处理")
    return {"result": "感谢您的好评！", "log": ["走正面路径"]}


def handle_negative(state: State) -> dict:
    print("[negative] 负面情感处理")
    return {"result": "抱歉给您带来不好的体验", "log": ["走负面路径"]}


def handle_neutral(state: State) -> dict:
    print("[neutral] 中性情感处理")
    return {"result": "感谢您的反馈", "log": ["走中性路径"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("analyze", analyze)
    graph.add_node("positive", handle_positive)
    graph.add_node("negative", handle_negative)
    graph.add_node("neutral", handle_neutral)

    graph.add_edge(START, "analyze")

    # 条件边：analyze 节点之后根据路由函数决定下一步
    # 参数：源节点, 路由函数, 路由映射 {路由返回值: 目标节点名}
    graph.add_conditional_edges(
        "analyze",
        sentiment_router,
        {
            "positive": "positive",
            "negative": "negative",
            "neutral": "neutral",
        },
    )

    # 三条路径都汇聚到 END
    graph.add_edge("positive", END)
    graph.add_edge("negative", END)
    graph.add_edge("neutral", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    test_cases = [
        "这个产品真棒！",
        "体验太差了",
        "还行吧，一般般",
    ]
    for text in test_cases:
        print(f"\n--- 输入: '{text}' ---")
        result = await app.ainvoke({"text": text, "sentiment": "", "result": "", "log": []})
        print(f"路由路径: {result['log']}")
        print(f"最终回复: {result['result']}")


if __name__ == "__main__":
    asyncio.run(main())
