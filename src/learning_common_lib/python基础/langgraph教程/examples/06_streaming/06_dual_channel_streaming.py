"""
06_streaming / 06_dual_channel_streaming

目标:
    演示 token 流和业务事件流双通道输出。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    独立的 token channel / progress channel

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/06_streaming/06_dual_channel_streaming.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/06_streaming/06_dual_channel_streaming.py

预期现象:
    1. 业务事件先告诉前端“当前在哪个阶段”
    2. token 通道只负责最终自然语言逐字输出

生产提醒:
    - 不要把结构化进度和 token chunk 混成一个事件流
    - 结构化事件适合 replay，token 流适合即时渲染
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator


def sse(channel: str, payload: dict) -> str:
    return f"event: {channel}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def progress_channel(request_id: str) -> AsyncIterator[str]:
    steps = [
        {"stage": "planning", "message": "已生成检索计划"},
        {"stage": "retrieval", "message": "已完成证据检索"},
        {"stage": "finalizing", "message": "正在组织最终回答"},
    ]
    for index, step in enumerate(steps, start=1):
        await asyncio.sleep(0.01)
        yield sse(
            "progress",
            {
                "id": index,
                "request_id": request_id,
                **step,
            },
        )


async def token_channel(text: str) -> AsyncIterator[str]:
    for token in text:
        await asyncio.sleep(0.005)
        yield sse("token", {"token": token})


async def main() -> None:
    request_id = "req-dual-channel-001"
    print("=== 业务事件通道 ===")
    async for item in progress_channel(request_id):
        print(item.strip())

    print("\n=== token 通道 ===")
    async for item in token_channel("差旅规则在近 30 天内发生了 2 处变更。"):
        print(item.strip())

    print("\n结论：")
    print("  - progress 适合前端进度条、断线回放、审计")
    print("  - token 适合聊天气泡逐字渲染，不适合做业务状态真理源")


if __name__ == "__main__":
    asyncio.run(main())
