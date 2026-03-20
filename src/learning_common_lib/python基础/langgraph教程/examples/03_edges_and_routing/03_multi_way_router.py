"""五路路由器（模拟 AgenticRAG step_gate_router）。

目标：实现多路条件路由，模拟真实 AgenticRAG 场景中的决策分发
关键 API：add_conditional_edges, 路由映射 dict
运行命令：python 03_multi_way_router.py
预期现象：根据 next_action 字段分发到 5 个不同处理节点，未知动作走 fallback
生产提醒：路由映射应覆盖所有可能的返回值，建议始终设置 fallback 兜底
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    query: str
    next_action: str
    response: str
    log: Annotated[list[str], operator.add]


# ---------- 五路路由函数 ----------
def step_gate_router(state: State) -> str:
    """AgenticRAG 风格的多路路由器。

    根据 state["next_action"] 分发到不同处理节点。
    生产环境中，next_action 通常由 LLM 决策生成。
    """
    action = state["next_action"]
    mapping = {
        "schedule": "scheduler",
        "replan": "replan",
        "clarify": "clarify",
        "finalize": "finalize",
        "output": "output",
    }
    return mapping.get(action, "fallback")


# ---------- 决策节点 ----------
def gate_node(state: State) -> dict:
    """决策节点：模拟 LLM 判断下一步动作。"""
    query = state["query"]
    # 简单规则模拟 LLM 决策
    if "安排" in query or "预约" in query:
        action = "schedule"
    elif "重新" in query:
        action = "replan"
    elif "?" in query or "？" in query or "什么" in query:
        action = "clarify"
    elif "总结" in query or "完成" in query:
        action = "finalize"
    elif "输出" in query or "结果" in query:
        action = "output"
    else:
        action = "unknown"
    print(f"[gate] query='{query}' -> action='{action}'")
    return {"next_action": action, "log": [f"决策: {action}"]}


# ---------- 处理节点 ----------
def scheduler_node(state: State) -> dict:
    print("[scheduler] 执行日程安排")
    return {"response": "已安排日程", "log": ["scheduler 处理"]}


def replan_node(state: State) -> dict:
    print("[replan] 重新规划")
    return {"response": "已重新规划方案", "log": ["replan 处理"]}


def clarify_node(state: State) -> dict:
    print("[clarify] 请求澄清")
    return {"response": "请提供更多细节", "log": ["clarify 处理"]}


def finalize_node(state: State) -> dict:
    print("[finalize] 最终确认")
    return {"response": "任务已完成", "log": ["finalize 处理"]}


def output_node(state: State) -> dict:
    print("[output] 输出结果")
    return {"response": "这是最终输出结果", "log": ["output 处理"]}


def fallback_node(state: State) -> dict:
    print("[fallback] 未知动作，走兜底逻辑")
    return {"response": "无法识别您的意图，请重试", "log": ["fallback 处理"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("gate", gate_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("replan", replan_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("output", output_node)
    graph.add_node("fallback", fallback_node)

    graph.add_edge(START, "gate")
    graph.add_conditional_edges(
        "gate",
        step_gate_router,
        {
            "scheduler": "scheduler",
            "replan": "replan",
            "clarify": "clarify",
            "finalize": "finalize",
            "output": "output",
            "fallback": "fallback",
        },
    )
    # 所有处理节点都汇聚到 END
    for node in ["scheduler", "replan", "clarify", "finalize", "output", "fallback"]:
        graph.add_edge(node, END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    test_queries = [
        "帮我安排明天的会议",
        "重新规划一下方案",
        "这是什么意思？",
        "总结一下今天的工作",
        "输出最终结果",
        "随便聊聊",  # 走 fallback
    ]
    for query in test_queries:
        print(f"\n--- 查询: '{query}' ---")
        result = await app.ainvoke({
            "query": query, "next_action": "", "response": "", "log": [],
        })
        print(f"路径: {result['log']}")
        print(f"回复: {result['response']}")


if __name__ == "__main__":
    asyncio.run(main())
