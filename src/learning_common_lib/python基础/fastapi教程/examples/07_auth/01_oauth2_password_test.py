"""
测试: 01_oauth2_password 路由——OAuth2 密码模式
运行命令: uv run python examples/07_auth/01_oauth2_password_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_oauth2_password.py")
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
        # 登录获取 token（OAuth2 用 form data）
        async with session.post(
            f"{base}/token",
            data={"username": "alice", "password": "alice123"},
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            token = data["access_token"]
            print(f"POST /token (alice) → {resp.status} {data}")

        # 用 token 访问受保护端点
        async with session.get(
            f"{base}/me", headers={"Authorization": f"Bearer {token}"}
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["username"] == "alice"
            print(f"GET /me (valid)     → {resp.status} {data}")

        # 无 token
        async with session.get(f"{base}/me") as resp:
            assert resp.status == 401
            print(f"GET /me (no token)  → {resp.status} (401)")

        # 错误密码
        async with session.post(
            f"{base}/token",
            data={"username": "alice", "password": "wrong"},
        ) as resp:
            assert resp.status == 401
            print(f"POST /token (wrong) → {resp.status} (401)")

    server.should_exit = True
    await task
    print("\n✓ 01_oauth2_password 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
