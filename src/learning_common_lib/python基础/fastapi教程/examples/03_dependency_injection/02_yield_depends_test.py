"""
测试: 02_yield_depends 路由——yield 依赖资源管理
运行命令: uv run python examples/03_dependency_injection/02_yield_depends_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_yield_depends.py")
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
        # 正常请求
        print("--- 正常请求 ---")
        async with session.get(f"{base}/data") as resp:
            assert resp.status == 200
            data = await resp.json()
            print(f"  响应: {resp.status} {data}\n")

        # 异常请求（连接仍会释放）
        print("--- 异常请求（连接仍会释放）---")
        async with session.get(f"{base}/error") as resp:
            assert resp.status == 500
            print(f"  响应: {resp.status}\n")

        # 再次正常请求（新连接）
        print("--- 再次正常请求（新连接）---")
        async with session.get(f"{base}/data") as resp:
            assert resp.status == 200
            data = await resp.json()
            print(f"  响应: {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 02_yield_depends 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
