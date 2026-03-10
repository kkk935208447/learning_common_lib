"""
测试: 01_hello_app 路由——aiohttp 自动验证
运行命令: uv run python examples/01_basics/01_hello_app_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# 导入同目录服务模块
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_hello_app.py")
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
        # 测试根路由
        async with session.get(f"{base}/") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["message"] == "Hello, FastAPI!"
            print(f"GET /            → {resp.status} {data}")

        # 测试动态路由
        async with session.get(f"{base}/hello/World") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["message"] == "Hello, World!"
            print(f"GET /hello/World → {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 01_hello_app 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
