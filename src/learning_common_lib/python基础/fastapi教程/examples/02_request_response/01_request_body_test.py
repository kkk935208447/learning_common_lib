"""
测试: 01_request_body 路由——请求体校验
运行命令: uv run python examples/02_request_response/01_request_body_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_request_body.py")
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
        # 合法请求
        async with session.post(
            f"{base}/items",
            json={"name": "Widget", "price": 9.99, "tags": ["sale"]},
        ) as resp:
            assert resp.status == 201
            data = await resp.json()
            assert data["name"] == "Widget"
            print(f"POST /items (valid)   → {resp.status} {data}")

        # 缺少必填字段
        async with session.post(
            f"{base}/items", json={"description": "no name"}
        ) as resp:
            assert resp.status == 422
            data = await resp.json()
            print(f"POST /items (missing) → {resp.status} errors={len(data['detail'])}")

        # 违反约束 price <= 0
        async with session.post(
            f"{base}/items", json={"name": "Bad", "price": -1}
        ) as resp:
            assert resp.status == 422
            print(f"POST /items (price<0) → {resp.status} (422)")

    server.should_exit = True
    await task
    print("\n✓ 01_request_body 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
