"""
06_streaming / 04_token_streaming

目标:
    演示真实 LLM 的异步 token 级流式输出，以及如何在 LangGraph / SSE 中复用。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    ChatOpenAI.astream
    AsyncCallbackHandler.on_llm_new_token
    app.astream(stream_mode="messages")     # 聊天界面流式输出 优先使用该方法
    app.astream_events(version="v2")        # 事件流实现流式输出，仅做演示，生产级不推荐，详情见：pitfalls.md 
    FastAPI StreamingResponse

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/06_streaming/04_token_streaming.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/06_streaming/04_token_streaming.py
    - 如需启动服务:
        uv run uvicorn src.learning_common_lib.python基础.langgraph教程.examples.06_streaming.04_token_streaming:app --reload
    - 健康检查:
        curl http://127.0.0.1:8000/health
    - SSE token 流:
        curl -N -G \
          -H "Accept: text/event-stream" \
          --data-urlencode "query=介绍一下 LangGraph 的 token streaming, 不少于3000字" \
          http://127.0.0.1:8000/stream

        curl -N -G \
          -H "Accept: text/event-stream" \
          --data-urlencode "query=1+1等于几？" \
          http://127.0.0.1:8000/stream


预期现象:
    1. 直接通过真实 ChatOpenAI.astream() 逐 token 输出
    2. 自定义 AsyncCallbackHandler 能收到真实 token
    3. 在 StateGraph 中通过 stream_mode="messages" 观察 token 流
    4. 在 astream_events(version="v2") 中看到 on_chat_model_stream 事件
    5. FastAPI /stream 可返回简单 SSE token 流

生产提醒:
    - token stream 只适合实时渲染，不适合 durable replay
    - replay 真理源应该是结构化业务事件，而不是 token chunk
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import LLMResult
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langchain_openai import ChatOpenAI


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


# ── 1. OpenAI 配置与模型构建 ───────────────────────────────
@dataclass(frozen=True)    # frozen=True 表示不可变数据类，更安全
class OpenAISettings:
    api_key: str | None
    base_url: str | None
    model: str
    temperature: float
    timeout_s: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def normalize_base_url(value: str | None) -> str | None:
    """兼容把完整 chat completions URL 误传进来的情况。"""
    if not value:
        return None

    normalized = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/v1/chat/completions"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len("/chat/completions")]
            break
    return normalized


def load_openai_settings() -> OpenAISettings:
    """ 加载 OpenAI 配置，支持从环境变量或 .env 文件中读取。"""
    api_key = (
        os.getenv("LANGGRAPH_TUTORIAL_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or None
    )
    raw_base_url = (
        os.getenv("LANGGRAPH_TUTORIAL_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LANGGRAPH_TUTORIAL_OPENAI_CHAT_COMPLETIONS_URL")
        or None
    )
    return OpenAISettings(
        api_key=api_key,
        base_url=normalize_base_url(raw_base_url),
        model=os.getenv("LANGGRAPH_TUTORIAL_OPENAI_MODEL", "gpt-4o-mini"),
        temperature=float(os.getenv("LANGGRAPH_TUTORIAL_OPENAI_TEMPERATURE", "0")),
        timeout_s=int(os.getenv("LANGGRAPH_TUTORIAL_OPENAI_TIMEOUT_S", "60")),
    )


def missing_config_message() -> str:
    return (
        "未检测到真实 OpenAI 配置。请设置 `OPENAI_API_KEY` 或 "
        "`LANGGRAPH_TUTORIAL_OPENAI_API_KEY`，如需代理还可设置 "
        "`OPENAI_BASE_URL` 或 `LANGGRAPH_TUTORIAL_OPENAI_BASE_URL`。"
    )


def build_chat_model(
    settings: OpenAISettings,
    *,
    callbacks: list[AsyncCallbackHandler] | None = None,   # langchain 回调函数，用于处理 LLM 的中间状态
) -> ChatOpenAI:
    """ 构建 ChatOpenAI 模型实例，支持回调函数。"""
    if not settings.configured:
        raise RuntimeError(missing_config_message())

    kwargs: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "temperature": settings.temperature,
        "timeout": settings.timeout_s,
        "streaming": True,
    }
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if callbacks:
        kwargs["callbacks"] = callbacks
    return ChatOpenAI(**kwargs)


def content_to_text(content: Any) -> str:
    """兼容 str / content blocks 两种返回格式。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class TokenStreamCallback(AsyncCallbackHandler):
    """ langchain 回调函数，用于处理 LLM 的中间状态 """

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """ 收到新 token 时的回调函数 """
        self.tokens.append(token)
        print(token, end="", flush=True)    # 流式打印 token

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """ 收到 LLM 结束时的回调函数 """
        print()


# ── 2. 构建最小 LangGraph ─────────────────────────────────
def build_token_graph(llm: ChatOpenAI) -> CompiledStateGraph:
    async def llm_node(state: MessagesState) -> dict:
        # 这里故意保留最小节点，只聚焦 token streaming 本身。
        response = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("llm", llm_node)
    graph.set_entry_point("llm")
    graph.add_edge("llm", END)
    return graph.compile()


# ── 3. 三种异步 token 流演示 ──────────────────────────────
async def demo_direct_astream(llm: ChatOpenAI, *, prompt: str) -> None:
    """ ChatOpenAI.astream 直接流式输出 """
    print("=== 1. ChatOpenAI.astream 直接流式输出 ===")
    collected: list[str] = []
    async for chunk in llm.astream([HumanMessage(content=prompt)]):
        text = content_to_text(getattr(chunk, "content", ""))
        if not text:
            continue
        collected.append(text)
        # 流式打印 token
        print(text, end="", flush=True)   
    print(f"\n完整输出长度: {len(''.join(collected))} 字符")


async def demo_callback_stream(settings: OpenAISettings, *, prompt: str) -> None:
    """ AsyncCallbackHandler 收到真实 token """
    print("\n=== 2. AsyncCallbackHandler 收到真实 token ===")
    callback = TokenStreamCallback()
    llm = build_chat_model(settings, callbacks=[callback])

    # 不使用 ainvoke(): ainvoke 会在内部聚合完整结果后才返回，虽然底层可能仍在流式拉取。
    # 这里显式走 astream，把 callback 与流式消费路径绑定到同一条语义清晰的代码路径上。
    collected: list[str] = []
    async for chunk in llm.astream([HumanMessage(content=prompt)]):
        text = content_to_text(getattr(chunk, "content", ""))
        if not text:
            continue
        collected.append(text)

    print(f"callback token 数: {len(callback.tokens)}")   # tokens 是上文自定义的回调函数中收集的 参数
    print(f"callback 拼接长度: {len(''.join(callback.tokens))}")
    print(f"stream 拼接长度: {len(''.join(collected))}")


async def demo_graph_message_stream(app: CompiledStateGraph, *, prompt: str) -> None:
    """ StateGraph.astream(stream_mode='messages'), langgraph 的流式输出 """
    print("\n=== 3. StateGraph.astream(stream_mode='messages') ===")
    token_buffer: list[str] = []
    async for chunk, metadata in app.astream(
        {"messages": [HumanMessage(content=prompt)]},
        config={"configurable": {"thread_id": "token-stream-demo"}},
        stream_mode="messages",
    ):
        text = content_to_text(getattr(chunk, "content", ""))
        if not text:
            continue
        token_buffer.append(text)
        # 流式打印 token
        print(
            f"[{metadata.get('langgraph_node', 'unknown')}] {text}",
            end="",
            flush=True,
        )
    print(f"\ngraph token 数: {len(token_buffer)}")


async def demo_graph_event_stream(app: CompiledStateGraph, *, prompt: str) -> None:
    """ astream_events(version='v2') / on_chat_model_stream, langgraph 的事件流 """
    print("\n=== 4. astream_events(version='v2') / on_chat_model_stream ===")
    event_count = 0
    token_buffer: list[str] = []
    async for event in app.astream_events(
        {"messages": [HumanMessage(content=prompt)]},
        config={"configurable": {"thread_id": "token-stream-events-demo"}},
        version="v2",
    ):
        if event["event"] != "on_chat_model_stream":
            continue
        chunk = event["data"].get("chunk")
        if not isinstance(chunk, AIMessageChunk):
            continue
        text = content_to_text(chunk.content)
        if not text:
            continue
        event_count += 1
        token_buffer.append(text)
        # 流式打印 token
        print(text, end="", flush=True)
    print(f"\non_chat_model_stream 事件数: {event_count}")
    print(f"拼接后长度: {len(''.join(token_buffer))} 字符")


# ── 4. FastAPI SSE 端点 ───────────────────────────────────
def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """保持教程里的简单 SSE 结构：event + data。"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_token_stream(query: str, *, thread_id: str = "token-stream-sse") -> AsyncGenerator[str, None]:
    """ LangGraph token stream SSE 端点 """
    settings = load_openai_settings()
    if not settings.configured:
        yield format_sse_event(
            "error",
            {"message": missing_config_message()},
        )
        return

    llm = build_chat_model(settings)
    graph_app = build_token_graph(llm)
    yield format_sse_event(
        "task.accepted",
        {
            "thread_id": thread_id,
            "status": "PENDING",
            "query": query,
            "message": "token stream accepted",
        },
    )

    async for chunk, metadata in graph_app.astream(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="messages",
    ):
        text = content_to_text(getattr(chunk, "content", ""))
        if not text:
            continue
        yield format_sse_event(
            "token",
            {
                "thread_id": thread_id,
                "node": metadata.get("langgraph_node"),
                "token": text,
            },
        )
        # 并不是“睡一会儿”，而是挂起当前协程并把控制权还给事件循环，下一次调度会尽快继续执行（零实际延时意义上的“可中断点”）:
        # 1. 协作式调度：若在一个 async for 里连续、极快地 yield，中间没有任何 await，当前协程会一直占着事件循环，其它协程（同进程其它请求、心跳等）难以及时运行。sleep(0) 是最轻量的让出点。
        # 2. 配合 StreamingResponse：每次 yield 之后给 ASGI/传输层一次调度机会，有利于把已产出的 SSE 片段更早送出去，减轻“多条 token 被攒成一大块再发”的主观感受（最终仍受 uvicorn、Nginx 缓冲等配置影响）。
        # 3. 与“完全无 await 的紧循环”对比：没有这类让出时，在 token 极快时客户端更容易感觉批量到达；加上 sleep(0) 是常见写法，代价很小。
        await asyncio.sleep(0)

    yield format_sse_event(
        "done",
        {
            "thread_id": thread_id,
            "status": "COMPLETED",
            "message": "token stream finished",
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title="LangGraph Token Streaming Demo")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        settings = load_openai_settings()
        return {
            "status": "ready" if settings.configured else "missing_llm_config",
            "configured": settings.configured,
            "model": settings.model,
            "base_url_configured": bool(settings.base_url),
        }

    @app.get("/stream")
    async def stream(query: str = Query(..., description="用户输入")) -> StreamingResponse:
        return StreamingResponse(
            sse_token_stream(query),
            media_type="text/event-stream",   # SSE 响应头
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()


# ── 5. CLI 入口 ───────────────────────────────────────────
async def main() -> None:
    settings = load_openai_settings()

    print("=== 真实异步 Token Streaming 演示 ===\n")
    if not settings.configured:
        print(missing_config_message())
        print("示例服务仍可启动，但 /stream 会返回 error 事件。")
        print(
            "启动方式: uvicorn "
            "src.learning_common_lib.python基础.langgraph教程.examples.06_streaming.04_token_streaming:app --reload"
        )
        print("测试命令:")
        print("  curl http://127.0.0.1:8000/health")
        print("  curl -N -G \\")
        print("    -H \"Accept: text/event-stream\" \\")
        print("    --data-urlencode \"query=介绍一下 LangGraph 的 token streaming\" \\")
        print("    http://127.0.0.1:8000/stream")
        return

    llm = build_chat_model(settings)
    prompt = "请用简洁中文介绍 LangGraph 的 token streaming 适用场景，并给出 2 个注意事项。"
    graph_app = build_token_graph(llm)

    await demo_direct_astream(llm, prompt=prompt)
    await demo_callback_stream(settings, prompt=prompt)
    await demo_graph_message_stream(graph_app, prompt=prompt)
    await demo_graph_event_stream(graph_app, prompt=prompt)

    print("\n=== 5. FastAPI SSE 入口 ===")
    print("  GET /health")
    print("  GET /stream?query=介绍一下 LangGraph 的 token streaming")
    print("  curl http://127.0.0.1:8000/health")
    print("  curl -N -G \\")
    print("    -H \"Accept: text/event-stream\" \\")
    print("    --data-urlencode \"query=介绍一下 LangGraph 的 token streaming\" \\")
    print("    http://127.0.0.1:8000/stream")
    print("提示: 生产环境应把 token 流和结构化事件流拆成两条通道。")


if __name__ == "__main__":
    asyncio.run(main())
