"""
04_tool_calling / 02_custom_tool_execution

目标:
    手动解析 tool_calls 并执行，理解 ToolMessage 构造细节

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    AIMessage.tool_calls, ToolMessage(tool_call_id=...)

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/04_tool_calling/02_custom_tool_execution.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/04_tool_calling/02_custom_tool_execution.py

预期现象:
    1. 手动解析 AIMessage 中的 tool_calls
    2. 根据工具名称路由到对应函数并执行
    3. 构造 ToolMessage 并回传，演示多工具并行调用

生产提醒:
    - tool_call_id 必须与 AIMessage 中的 id 一一对应，否则 LLM 无法关联结果
    - 并行调用多个工具时，所有 ToolMessage 应一次性追加到消息列表
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph


# ── 1. 定义工具 ──────────────────────────────────────────────
@tool
def get_weather(city: str) -> str:
    """获取指定城市的天气信息"""
    weather_db = {"北京": "晴天 25°C", "上海": "多云 22°C", "深圳": "小雨 28°C"}
    return weather_db.get(city, f"{city}: 暂无数据")


@tool
def get_population(city: str) -> str:
    """获取指定城市的人口信息"""
    pop_db = {"北京": "2189万", "上海": "2487万", "深圳": "1756万"}
    return pop_db.get(city, f"{city}: 暂无数据")


# 工具注册表：名称 -> 可调用对象
TOOL_REGISTRY: dict[str, callable] = {
    "get_weather": get_weather,
    "get_population": get_population,
}


# ── 2. 手动执行工具调用 ─────────────────────────────────────
def custom_tool_executor(state: MessagesState) -> dict:
    """手动解析 tool_calls 并执行，构造 ToolMessage 列表"""
    last_message = state["messages"][-1]
    assert isinstance(last_message, AIMessage), "最后一条消息必须是 AIMessage"

    tool_messages: list[ToolMessage] = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        call_id = tool_call["id"]  # 必须与 AIMessage 中的 id 匹配

        print(f"  执行工具: {tool_name}({tool_args}), call_id={call_id}")

        if tool_name in TOOL_REGISTRY:
            # invoke() 是 @tool 装饰器提供的标准调用方式
            result = TOOL_REGISTRY[tool_name].invoke(tool_args)
        else:
            result = f"错误: 未知工具 '{tool_name}'"

        # 构造 ToolMessage，tool_call_id 是关键字段
        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=call_id, name=tool_name)
        )

    return {"messages": tool_messages}


def main() -> None:
    # ── 3. 模拟 LLM 返回多工具并行调用 ──────────────────────
    # 真实场景：LLM 可能在一次回复中请求调用多个工具（并行调用）
    fake_ai_message = AIMessage(
        content="让我同时查询北京的天气和人口",
        tool_calls=[
            {"id": "call_w1", "name": "get_weather", "args": {"city": "北京"}},
            {"id": "call_p1", "name": "get_population", "args": {"city": "北京"}},
        ],
    )

    print("=== 模拟并行工具调用 ===")
    print(f"LLM 请求调用 {len(fake_ai_message.tool_calls)} 个工具:")
    for tc in fake_ai_message.tool_calls:
        print(f"  - {tc['name']}({tc['args']})")

    # ── 4. 在 StateGraph 中使用自定义执行器 ──────────────────
    call_count = 0

    def fake_llm_node(state: MessagesState) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 第一轮：请求并行调用两个工具
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "call_w1", "name": "get_weather", "args": {"city": "上海"}},
                            {"id": "call_p1", "name": "get_population", "args": {"city": "上海"}},
                        ],
                    )
                ]
            }
        # 第二轮：不再调用工具，给出最终回答
        return {"messages": [AIMessage(content="上海天气多云22°C，人口2487万。")]}

    def should_continue(state: MessagesState) -> str | END:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("llm", fake_llm_node)
    graph.add_node("tools", custom_tool_executor)
    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})  # 需要显示执行路由节点，以免出现错误
    graph.add_edge("tools", "llm")

    app = graph.compile()
    get_langgraph_png(app, "02_custom_tool_execution.png")    # 导出图

    print("\n=== 完整图执行 ===")
    result = app.invoke({"messages": [HumanMessage(content="上海的天气和人口是多少？")]})
    print("\n=== 最终消息列表 ===")
    print(f"result: {result}")
    print("\n\n")

    for msg in result["messages"]:
        role = type(msg).__name__
        # content = msg.content or str(msg.tool_calls)
        # print(f"  [{role}] {content}")
        print(f"  [{role}] {msg}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    # 画图 png
    app.get_graph().draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    main()
