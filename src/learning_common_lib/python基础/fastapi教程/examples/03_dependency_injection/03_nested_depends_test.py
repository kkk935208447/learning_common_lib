"""
测试: 03_nested_depends 路由——依赖链 auth → user → permission
运行命令: uv run python examples/03_dependency_injection/03_nested_depends_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_nested_depends.py")
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
        # admin 访问 profile
        async with session.get(
            f"{base}/profile", headers={"Authorization": "Bearer token_admin"}
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["user"]["username"] == "admin"
            print(f"GET /profile (admin)  → {resp.status} {data}")

        # viewer 访问 profile
        async with session.get(
            f"{base}/profile", headers={"Authorization": "Bearer token_viewer"}
        ) as resp:
            assert resp.status == 200
            print(f"GET /profile (viewer) → {resp.status} {(await resp.json())}")

        # 无效 token
        async with session.get(
            f"{base}/profile", headers={"Authorization": "Bearer bad_token"}
        ) as resp:
            assert resp.status == 401
            print(f"GET /profile (bad)    → {resp.status} (401)")

        # admin 执行管理操作
        async with session.delete(
            f"{base}/admin/cleanup", headers={"Authorization": "Bearer token_admin"}
        ) as resp:
            assert resp.status == 200
            print(f"DELETE /admin (admin) → {resp.status} {(await resp.json())}")

        # viewer 尝试管理操作
        async with session.delete(
            f"{base}/admin/cleanup", headers={"Authorization": "Bearer token_viewer"}
        ) as resp:
            assert resp.status == 403
            print(f"DELETE /admin (viewer)→ {resp.status} (403)")

    server.should_exit = True
    await task
    print("\n✓ 03_nested_depends 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
