"""
测试: 02_response_model 路由——响应模型过滤敏感字段
运行命令: uv run python examples/02_request_response/02_response_model_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_response_model.py")
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
        # 创建用户
        async with session.post(f"{base}/users", json={
            "username": "alice", "email": "alice@example.com", "password": "secret123"
        }) as resp:
            assert resp.status == 201
            data = await resp.json()
            assert "password_hash" not in data, "password_hash 不应出现在响应中！"
            assert "password" not in data
            print(f"POST /users  → {resp.status} {data}")
            print("  ✓ password_hash 已被过滤")

        # 查询用户
        async with session.get(f"{base}/users/1") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "password_hash" not in data
            print(f"GET /users/1 → {resp.status} {data}")

        # 404
        async with session.get(f"{base}/users/999") as resp:
            assert resp.status == 404
            print(f"GET /users/999 → {resp.status} (404)")

    server.should_exit = True
    await task
    print("\n✓ 02_response_model 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
