"""
04_tool_calling / 04_react_agent_pattern

目标:
    实现完整的 ReAct Agent 模式——思考→工具→观察循环

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    条件边 + ToolNode + LLM 节点, should_continue 路由函数

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/04_tool_calling/04_react_agent_pattern.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/04_tool_calling/04_react_agent_pattern.py

预期现象:
    1. Agent 接收用户问题
    2. LLM 决定调用工具（思考→行动）
    3. 工具返回结果（观察）
    4. LLM 根据观察决定是否继续调用工具或给出最终回答
    5. 循环直到 LLM 不再请求工具调用

生产提醒:
    - 真实场景替换 FakeListChatModel 为 ChatOpenAI / ChatAnthropic
    - 务必设置最大迭代次数防止无限循环（recursion_limit）
    - should_continue 是 ReAct 模式的核心路由逻辑
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


# ── 1. 定义工具集 ────────────────────────────────────────────
@tool
def search_knowledge(query: str) -> str:
    """搜索知识库，返回相关信息"""
    kb = {
        "langgraph": "LangGraph 是基于 LangChain 的有状态 Agent 编排框架",
        "react": "ReAct = Reasoning + Acting，让 LLM 交替进行推理和工具调用",
        "python版本": "当前推荐 Python 3.11+",
    }
    for key, val in kb.items():
        if key in query.lower():
            return val
    return f"未找到与 '{query}' 相关的信息"


@tool
def get_current_date() -> str:
    """获取当前日期"""
    return "2026-03-19"


tools = [search_knowledge, get_current_date]


# ── 2. 核心路由函数 ──────────────────────────────────────────
def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    """ReAct 模式的核心：判断 LLM 是否还需要调用工具
    - 如果最后一条 AIMessage 包含 tool_calls → 继续到 tools 节点
    - 否则 → 结束循环
    """
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END


def main() -> None:
    # ── 3. 模拟多轮 ReAct 循环 ──────────────────────────────
    # 模拟 LLM 的行为序列：
    #   轮次1: 调用 search_knowledge
    #   轮次2: 调用 get_current_date
    #   轮次3: 综合所有观察，给出最终回答
    step = 0

    def fake_llm_node(state: MessagesState) -> dict:
        nonlocal step
        step += 1

        if step == 1:
            # 思考：需要先查询 LangGraph 信息
            print("  [思考] 用户问的是 LangGraph，我需要搜索知识库")
            return {
                "messages": [
                    AIMessage(
                        content="让我先搜索一下 LangGraph 的信息",
                        tool_calls=[
                            {"id": "call_s1", "name": "search_knowledge",
                             "args": {"query": "langgraph"}},
                        ],
                    )
                ]
            }

        if step == 2:
            # 观察到搜索结果后，决定再获取日期
            last_tool_result = state["messages"][-1]
            print(f"  [观察] 搜索结果: {last_tool_result.content}")
            print("  [思考] 还需要获取当前日期来补充回答")
            return {
                "messages": [
                    AIMessage(
                        content="搜索到了信息，再获取一下当前日期",
                        tool_calls=[
                            {"id": "call_d1", "name": "get_current_date", "args": {}},
                        ],
                    )
                ]
            }

        # 轮次3：综合所有观察，给出最终回答（不再调用工具）
        # 收集之前的工具结果
        tool_results = [
            msg.content for msg in state["messages"] if isinstance(msg, ToolMessage)
        ]
        print(f"  [观察] 日期结果: {state['messages'][-1].content}")
        print("  [思考] 信息足够了，生成最终回答")
        final_answer = (
            f"综合查询结果：\n"
            f"1. {tool_results[0]}\n"
            f"2. 当前日期: {tool_results[1]}\n"
            f"以上就是关于 LangGraph 的信息。"
        )
        return {"messages": [AIMessage(content=final_answer)]}

    # ── 4. 构建 ReAct Agent 图 ──────────────────────────────
    graph = StateGraph(MessagesState)
    graph.add_node("agent", fake_llm_node)  # LLM 节点（思考+决策）
    graph.add_node("tools", ToolNode(tools))  # 工具执行节点
    graph.set_entry_point("agent")

    # 条件边：agent 决定是否继续调用工具
    graph.add_conditional_edges("agent", should_continue)
    # 工具执行完毕后回到 agent（观察→思考）
    graph.add_edge("tools", "agent")

    app = graph.compile()

    # ── 5. 运行 Agent ───────────────────────────────────────
    print("=== ReAct Agent 执行过程 ===\n")
    result = app.invoke(
        {"messages": [HumanMessage(content="介绍一下 LangGraph，顺便告诉我今天日期")]},
        config={"recursion_limit": 10},  # 安全阀
    )

    print("\n=== 完整消息流 ===")
    for i, msg in enumerate(result["messages"]):
        role = type(msg).__name__
        content = msg.content[:100] if msg.content else str(msg.tool_calls)
        print(f"  {i}. [{role}] {content}")

    print(f"\n总共经历 {step} 轮 LLM 调用（2 轮工具调用 + 1 轮最终回答）")


if __name__ == "__main__":
    main()
