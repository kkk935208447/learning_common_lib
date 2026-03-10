"""
测试: 02_jwt_bearer 路由——JWT 签发与验证
运行命令: uv run python examples/07_auth/02_jwt_bearer_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
import time
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_jwt_bearer.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
create_jwt = _svc.create_jwt


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
        # 登录
        async with session.post(
            f"{base}/token", data={"username": "alice", "password": "alice123"}
        ) as resp:
            assert resp.status == 200
            jwt_token = (await resp.json())["access_token"]
            print(f"POST /token → {resp.status}")
            print(f"  JWT: {jwt_token[:50]}...")

        headers = {"Authorization": f"Bearer {jwt_token}"}

        # 解码验证
        async with session.get(f"{base}/me", headers=headers) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["username"] == "alice"
            print(f"GET /me     → {resp.status} {data}")

        async with session.get(f"{base}/admin", headers=headers) as resp:
            assert resp.status == 200
            print(f"GET /admin  → {resp.status} {await resp.json()}")

        # 伪造 token
        async with session.get(
            f"{base}/me", headers={"Authorization": "Bearer fake.token.here"}
        ) as resp:
            assert resp.status == 401
            print(f"GET /me (fake) → {resp.status} (401)")

        # 过期 token
        expired_payload = {"sub": "alice", "role": "admin", "exp": time.time() - 10}
        expired_token = create_jwt(expired_payload)
        async with session.get(
            f"{base}/me", headers={"Authorization": f"Bearer {expired_token}"}
        ) as resp:
            assert resp.status == 401
            print(f"GET /me (expired) → {resp.status} (401)")

    server.should_exit = True
    await task
    print("\n✓ 02_jwt_bearer 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
