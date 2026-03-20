"""@task 定义可检查点的子任务

目标：
    演示 @task 装饰器将函数标记为可检查点的子任务，
    任务执行结果自动持久化，失败后可从断点恢复。

关键 API：
    - @task —— 标记可检查点的子任务
    - @entrypoint —— 工作流入口（组合多个 task）

运行命令：
    python 02_task_decorator.py

预期现象：
    多个 @task 子任务依次执行，每个任务完成后自动 checkpoint。
    模拟中断恢复场景。

生产提醒：
    - @task 的参数和返回值必须可序列化（JSON-safe）
    - 每个 @task 完成后自动创建 checkpoint，粒度比节点级更细
    - @task 内部不应有副作用（如发送邮件），否则恢复时会重复执行
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.func import entrypoint, task


# ── 子任务定义 ──────────────────────────────────────────
@task
def extract_keywords(text: str) -> list[str]:
    """提取关键词（自动 checkpoint）"""
    print(f"  [task:extract] 从文本提取关键词...")
    # 模拟关键词提取
    keywords = [w for w in text.split() if len(w) > 2][:5]
    print(f"  [task:extract] 关键词: {keywords}")
    return keywords


@task
def generate_summary(text: str) -> str:
    """生成摘要（自动 checkpoint）"""
    print(f"  [task:summary] 生成摘要...")
    # 使用 FakeListChatModel 模拟
    # 生产环境替换为: ChatOpenAI(model="gpt-4o")
    llm = FakeListChatModel(responses=[f"摘要: {text[:50]}..."])
    result = llm.invoke(text)
    print(f"  [task:summary] {result.content}")
    return result.content


@task
def classify_sentiment(text: str) -> str:
    """情感分类（自动 checkpoint）"""
    print(f"  [task:sentiment] 分析情感...")
    # 简单模拟
    if any(w in text for w in ["好", "棒", "优秀", "喜欢"]):
        sentiment = "positive"
    elif any(w in text for w in ["差", "糟", "失败", "讨厌"]):
        sentiment = "negative"
    else:
        sentiment = "neutral"
    print(f"  [task:sentiment] 结果: {sentiment}")
    return sentiment


# ── 工作流入口 ──────────────────────────────────────────
checkpointer = MemorySaver()


@entrypoint(checkpointer=checkpointer)
def analyze_document(text: str) -> dict:
    """文档分析工作流：组合多个 @task 子任务

    每个 task 完成后自动 checkpoint，如果中途失败，
    恢复时会跳过已完成的 task，从断点继续。
    """
    print("[workflow] 开始文档分析")

    # 调用 task 时需要 .result() 获取返回值
    keywords_future = extract_keywords(text)
    summary_future = generate_summary(text)
    sentiment_future = classify_sentiment(text)

    # 获取结果（每个 task 完成后自动 checkpoint）
    keywords = keywords_future.result()
    summary = summary_future.result()
    sentiment = sentiment_future.result()

    result = {
        "keywords": keywords,
        "summary": summary,
        "sentiment": sentiment,
    }
    print(f"[workflow] 分析完成")
    return result


if __name__ == "__main__":
    async def main() -> None:
        print("=== @task 子任务演示 ===\n")

        text = "LangGraph 是一个非常好的框架 用于构建有状态的 AI 应用程序"
        config = {"configurable": {"thread_id": "task-demo-1"}}

        result = await analyze_document.ainvoke(text, config=config)

        print(f"\n最终结果:")
        print(f"  关键词: {result['keywords']}")
        print(f"  摘要: {result['summary']}")
        print(f"  情感: {result['sentiment']}")

    asyncio.run(main())
