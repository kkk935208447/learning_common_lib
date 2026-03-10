"""
测试: 01_exception_handlers 路由——统一错误格式
运行命令: uv run python examples/04_middleware_errors/01_exception_handlers_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_exception_handlers.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
register_exception_handlers = _svc.register_exception_handlers


async def main() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        # 正常
        async with session.get(f"{base}/items/1") as resp:
            assert resp.status == 200
            print(f"GET /items/1   → {resp.status} {await resp.json()}")

        # 业务异常 404
        async with session.get(f"{base}/items/999") as resp:
            assert resp.status == 404
            data = await resp.json()
            assert data["code"] == "NOT_FOUND"
            print(f"GET /items/999 → {resp.status} {data}")

        # 校验错误 422
        async with session.post(
            f"{base}/items", json={"name": "", "price": -1}
        ) as resp:
            assert resp.status == 422
            data = await resp.json()
            assert data["code"] == "VALIDATION_ERROR"
            print(f"POST /items    → {resp.status} code={data['code']}")

    server.should_exit = True
    await task
    print("\n✓ 01_exception_handlers 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
