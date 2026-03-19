"""@entrypoint 定义工作流入口

目标：
    演示 LangGraph Functional API 的 @entrypoint 装饰器，
    用原生 Python if/for 控制流定义工作流，无需显式构建图。

关键 API：
    - @entrypoint(checkpointer) —— 定义工作流入口函数
    - 原生 Python 控制流（if/for/while）

运行命令：
    python 01_entrypoint_basics.py

预期现象：
    使用 @entrypoint 定义的工作流像普通函数一样执行，
    但自动获得 checkpoint 持久化能力。

生产提醒：
    - @entrypoint 适合简单线性流程，复杂拓扑仍建议用 Graph API
    - entrypoint 函数的参数和返回值必须可序列化
    - checkpointer 可选，不传则无持久化
"""
from __future__ import annotations

from langchain_community.chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.func import entrypoint


# ── 工作流定义 ──────────────────────────────────────────
checkpointer = MemorySaver()


@entrypoint(checkpointer=checkpointer)
def classify_and_respond(query: str) -> str:
    """使用原生 Python 控制流的工作流

    @entrypoint 让这个函数自动获得：
    - checkpoint 持久化
    - 可中断/恢复
    - 状态追踪
    """
    print(f"[entrypoint] 收到查询: {query}")

    # 原生 if 控制流 —— 无需 conditional_edges
    if "价格" in query or "多少钱" in query:
        category = "pricing"
    elif "故障" in query or "报错" in query:
        category = "support"
    else:
        category = "general"

    print(f"[entrypoint] 分类为: {category}")

    # 使用 FakeListChatModel 模拟 LLM
    # 生产环境替换为: ChatOpenAI(model="gpt-4o")
    responses_map = {
        "pricing": "我们的产品价格从 99 元起，具体取决于您的需求。",
        "support": "请提供错误日志，我来帮您排查问题。",
        "general": "感谢您的咨询，请问有什么可以帮助您的？",
    }
    llm = FakeListChatModel(responses=[responses_map[category]])
    result = llm.invoke(query)

    return f"[{category}] {result.content}"


@entrypoint(checkpointer=checkpointer)
def batch_processor(items: list[str]) -> list[str]:
    """使用原生 for 循环的批处理工作流"""
    results = []

    # 原生 for 循环 —— 无需 Send API
    for i, item in enumerate(items):
        print(f"[batch] 处理第 {i + 1}/{len(items)} 项: {item}")
        processed = item.upper()
        results.append(processed)

        # 原生条件判断
        if len(results) >= 3:
            print("[batch] 达到批次上限，提前结束")
            break

    return results


if __name__ == "__main__":
    # ── 演示 1：分类响应工作流 ──
    print("=== @entrypoint 分类响应 ===\n")
    config = {"configurable": {"thread_id": "ep-demo-1"}}

    queries = ["这个产品多少钱？", "系统报错了怎么办？", "你好"]
    for q in queries:
        result = classify_and_respond.invoke(q, config=config)
        print(f"  结果: {result}\n")

    # ── 演示 2：批处理工作流 ──
    print("=== @entrypoint 批处理 ===\n")
    config2 = {"configurable": {"thread_id": "ep-demo-2"}}
    items = ["任务a", "任务b", "任务c", "任务d"]
    result = batch_processor.invoke(items, config=config2)
    print(f"  批处理结果: {result}")
