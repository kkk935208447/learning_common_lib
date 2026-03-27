"""
06_streaming / 04_token_streaming

目标:
    演示 LLM token 级流式输出 + 自定义回调处理

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    astream_events + on_chat_model_stream 事件

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/06_streaming/04_token_streaming.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/06_streaming/04_token_streaming.py
    - 如需启动服务:
        uvicorn src.learning_common_lib.python基础.langgraph教程.examples.06_streaming.04_token_streaming:app --reload

预期现象:
    1. 逐 token 输出 LLM 生成的内容（模拟）
    2. 自定义回调处理 token 流
    3. 参考 AgenticRAG SSE 实现的 token 流式推送模式

生产提醒:
    - 真实场景需要替换为支持流式的 LLM（如 ChatOpenAI(streaming=True)）
    - FakeListChatModel 不支持真正的 token 流式，此处模拟演示
    - SSE 推送时注意设置正确的 Content-Type: text/event-stream
    - 此文件使用异步 API，需要 asyncio 运行
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import LLMResult
from langgraph.graph import END, MessagesState, StateGraph


# ── 1. 自定义流式回调 ───────────────────────────────────────
class TokenStreamCallback(AsyncCallbackHandler):
    """自定义回调：收集 token 流，可用于 SSE 推送"""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def on_llm_new_token(self, token: str, **kwargs: object) -> None:
        """每个新 token 到达时触发"""
        self.tokens.append(token)
        # 生产环境：这里可以推送到 SSE / WebSocket
        print(token, end="", flush=True)

    async def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        print()  # 换行


# ── 2. 模拟 token 级流式输出 ────────────────────────────────
async def simulate_token_stream(text: str, delay: float = 0.05) -> AsyncIterator[str]:
    """模拟 LLM 逐 token 输出"""
    for char in text:
        await asyncio.sleep(delay)
        yield char


def fake_llm_node(state: MessagesState) -> dict:
    """模拟 LLM 节点（同步版本，用于图节点）"""
    return {
        "messages": [
            AIMessage(content="LangGraph 是一个强大的 Agent 编排框架，支持流式输出。")
        ]
    }


# ── 3. SSE 格式化工具 ──────────────────────────────────────
def format_sse_event(event_type: str, data: str) -> str:
    """将数据格式化为 SSE 事件格式（参考 AgenticRAG 实现）"""
    return f"event: {event_type}\ndata: {data}\n\n"


async def main() -> None:
    # ── 4. 模拟 token 流式输出 ──────────────────────────────
    print("=== 模拟 Token 级流式输出 ===")
    print("输出: ", end="")
    full_text = ""
    async for token in simulate_token_stream("LangGraph 支持 token 级别的流式输出，适合实时 UI 场景。"):
        print(token, end="", flush=True)
        full_text += token
    print(f"\n完整文本长度: {len(full_text)} 字符")

    # ── 5. 在 StateGraph 中使用 astream_events 捕获流 ──────
    print("\n=== astream_events 捕获 token 流 ===")
    graph = StateGraph(MessagesState)
    graph.add_node("llm", fake_llm_node)
    graph.set_entry_point("llm")
    graph.add_edge("llm", END)
    app = graph.compile()

    # 使用 astream_events 监听所有事件
    token_buffer: list[str] = []
    async for event in app.astream_events(
        {"messages": [HumanMessage(content="介绍 LangGraph")]},
        version="v2",
    ):
        # 在真实 LLM 场景下，on_chat_model_stream 会逐 token 触发
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                token_buffer.append(chunk.content)
                print(chunk.content, end="", flush=True)

    if not token_buffer:
        print("  (FakeListChatModel 不产生 on_chat_model_stream 事件)")
        print("  真实 LLM 场景下，这里会逐 token 输出")

    # ── 6. SSE 推送模式演示 ─────────────────────────────────
    print("\n\n=== SSE 推送格式演示 ===")
    sample_tokens = ["Lang", "Graph", " 是", "一个", "框架"]
    for token in sample_tokens:
        sse = format_sse_event("token", token)
        print(f"  {sse.strip()}")

    # 结束事件
    print(f"  {format_sse_event('done', '[DONE]').strip()}")

    print("\n提示: 生产环境使用 ChatOpenAI(streaming=True) 获得真正的 token 流")
    print("参考: AgenticRAG 的 SSE 实现使用 astream_events 配合 FastAPI StreamingResponse")


if __name__ == "__main__":
    asyncio.run(main())
