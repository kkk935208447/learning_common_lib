"""
测试: 01_basic_depends 路由——分页依赖复用
运行命令: uv run python examples/03_dependency_injection/01_basic_depends_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_basic_depends.py")
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
        async with session.get(f"{base}/items", params={"skip": 0, "limit": 3}) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data["data"]) == 3
            print(f"GET /items?limit=3 → {resp.status} got={len(data['data'])}")

        async with session.get(f"{base}/users", params={"skip": 5, "limit": 2}) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data["data"]) == 2
            assert data["data"][0]["username"] == "user_5"
            print(f"GET /users?skip=5&limit=2 → {resp.status} first={data['data'][0]['username']}")

        # 共享校验：limit 超限
        async with session.get(f"{base}/items", params={"limit": 200}) as resp:
            assert resp.status == 422
            print(f"GET /items?limit=200 → {resp.status} (422)")

    server.should_exit = True
    await task
    print("\n✓ 01_basic_depends 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
