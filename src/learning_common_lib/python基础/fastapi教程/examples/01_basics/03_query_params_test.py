"""
测试: 03_query_params 路由——查询参数与分页
运行命令: uv run python examples/01_basics/03_query_params_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_query_params.py")
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
        # 默认分页
        async with session.get(f"{base}/items") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["total"] == 50
            assert len(data["data"]) == 10
            print(f"GET /items           → {resp.status} total={data['total']} got={len(data['data'])}")

        # 自定义分页
        async with session.get(f"{base}/items", params={"skip": 5, "limit": 3}) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data["data"]) == 3
            assert data["data"][0]["id"] == 5
            print(f"GET /items?skip=5&limit=3 → {resp.status} first_id={data['data'][0]['id']}")

        # 搜索
        async with session.get(f"{base}/items", params={"q": "item_1", "limit": 100}) as resp:
            assert resp.status == 200
            data = await resp.json()
            print(f"GET /items?q=item_1  → {resp.status} matched={len(data['data'])}")

        # 违反约束 limit=-1
        async with session.get(f"{base}/items", params={"limit": -1}) as resp:
            assert resp.status == 422
            print(f"GET /items?limit=-1  → {resp.status} (422 校验失败)")

    server.should_exit = True
    await task
    print("\n✓ 03_query_params 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
