"""运行时配置切换图行为

目标：
    演示通过 configurable 字段在运行时动态切换图的行为，
    同一张图可以根据不同配置产生不同的执行路径和结果。

关键 API：
    - RunnableConfig["configurable"] —— 运行时配置字典
    - graph.ainvoke(state, config={"configurable": {...}})

运行命令：
    python 03_configurable_graph.py

预期现象：
    同一张图分别以 "详细模式" 和 "简洁模式" 运行，输出不同风格的结果。

生产提醒：
    - configurable 适合 A/B 测试、多租户配置、模型切换等场景
    - 配置值在整个图执行期间保持不变，所有节点共享同一份 config
    - 生产环境建议对 configurable 字段做 schema 校验
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph


class State(TypedDict):
    query: str
    response: str
    style: str


def analyze_node(state: State, config: RunnableConfig) -> dict:
    """从 config 中读取运行时配置"""
    cfg = config.get("configurable", {})
    style = cfg.get("response_style", "详细")
    model_name = cfg.get("model_name", "fake-model")
    print(f"[analyze] 配置 -> 风格: {style}, 模型: {model_name}")
    return {"style": style}


def generate_node(state: State, config: RunnableConfig) -> dict:
    """根据配置生成不同风格的回复"""
    style = state["style"]

    if style == "简洁":
        fake_responses = ["Python 是一种编程语言。"]
    else:
        fake_responses = [
            "Python 是一种广泛使用的高级编程语言，由 Guido van Rossum 于 1991 年创建。"
            "它以简洁的语法和强大的生态系统著称，广泛应用于 Web 开发、数据科学、"
            "人工智能等领域。"
        ]

    llm = FakeListChatModel(responses=fake_responses)
    result = llm.invoke(state["query"])
    print(f"[generate] 风格={style}, 回复长度={len(result.content)}")
    return {"response": result.content}


def build_configurable_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate", generate_node)
    graph.set_entry_point("analyze")
    graph.add_edge("analyze", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


if __name__ == "__main__":
    async def main() -> None:
        app = build_configurable_graph()
        query = "什么是 Python？"

        print("=== 配置 A: 详细模式 ===")
        config_a = {"configurable": {"response_style": "详细", "model_name": "gpt-4o"}}
        result_a = await app.ainvoke({"query": query, "response": "", "style": ""}, config=config_a)
        print(f"回复: {result_a['response']}\n")

        print("=== 配置 B: 简洁模式 ===")
        config_b = {"configurable": {"response_style": "简洁", "model_name": "gpt-4o-mini"}}
        result_b = await app.ainvoke({"query": query, "response": "", "style": ""}, config=config_b)
        print(f"回复: {result_b['response']}\n")

        print("同一张图，不同配置，不同行为 —— 这就是 configurable 的威力")

    asyncio.run(main())
