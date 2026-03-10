"""
测试: 02_sse_streaming 路由——SSE 流式响应
运行命令: uv run python examples/06_background_streaming/02_sse_streaming_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_sse_streaming.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router


async def main() -> None:
    app = FastAPI()
    app.include_router(router)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        # 流式读取 SSE
        print("--- SSE 流式输出 ---")
        chunks = []
        async with session.get(f"{base}/chat/stream", params={"prompt": "异步编程"}) as resp:
            assert resp.status == 200
            async for line in resp.content:
                text = line.decode().strip()
                if text.startswith("data: "):
                    data = text[6:]
                    chunks.append(data)
                    print(f"  收到: {data}")
        assert "[DONE]" in chunks
        print(f"  共收到 {len(chunks)} 个块")

        # 倒计时
        print("\n--- 倒计时 ---")
        async with session.get(f"{base}/countdown", params={"n": 3}) as resp:
            assert resp.status == 200
            async for line in resp.content:
                text = line.decode().strip()
                if text.startswith("data: "):
                    print(f"  {text[6:]}")

    server.should_exit = True
    await task
    print("\n✓ 02_sse_streaming 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
