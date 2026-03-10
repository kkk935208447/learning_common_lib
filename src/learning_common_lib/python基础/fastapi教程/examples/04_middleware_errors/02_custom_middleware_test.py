"""
测试: 02_custom_middleware 路由——请求耗时中间件
运行命令: uv run python examples/04_middleware_errors/02_custom_middleware_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_custom_middleware.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
TimingMiddleware = _svc.TimingMiddleware


async def main() -> None:
    app = FastAPI()
    app.add_middleware(TimingMiddleware)
    app.include_router(router)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/fast") as resp:
            assert resp.status == 200
            process_time = resp.headers.get("X-Process-Time")
            assert process_time is not None
            print(f"GET /fast → {resp.status} X-Process-Time: {process_time}")

        async with session.get(f"{base}/slow") as resp:
            assert resp.status == 200
            process_time = resp.headers.get("X-Process-Time")
            assert process_time is not None
            print(f"GET /slow → {resp.status} X-Process-Time: {process_time}")

    server.should_exit = True
    await task
    print("\n✓ 02_custom_middleware 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
