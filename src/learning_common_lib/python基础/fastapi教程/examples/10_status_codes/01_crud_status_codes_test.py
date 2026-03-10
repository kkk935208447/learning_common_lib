"""
测试: 01_crud_status_codes 路由——201 / 204 / 400 / 404 / 409 / 422
运行命令: uv run python examples/10_status_codes/01_crud_status_codes_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_crud_status_codes.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
register_status_exception_handlers = _svc.register_status_exception_handlers


async def main() -> None:
    app = FastAPI()
    register_status_exception_handlers(app)
    app.include_router(router)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base}/test/reset") as resp:
            assert resp.status == 204

        # 201 Created
        async with session.post(
            f"{base}/users",
            json={"username": "alice", "email": "alice@example.com"},
        ) as resp:
            assert resp.status == 201
            data = await resp.json()
            assert data == {
                "code": 0,
                "message": "用户创建成功",
                "data": {"username": "alice", "email": "alice@example.com"},
            }
            print(f"POST /users (create)     → {resp.status} {data}")

        # 409 Conflict
        async with session.post(
            f"{base}/users",
            json={"username": "alice", "email": "alice@example.com"},
        ) as resp:
            assert resp.status == 409
            data = await resp.json()
            assert data == {
                "code": 40901,
                "message": "用户名已存在",
                "data": None,
            }
            print(f"POST /users (duplicate)  → {resp.status} {data}")

        # 200 OK
        async with session.get(f"{base}/users/alice") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["code"] == 0
            assert data["data"]["username"] == "alice"
            print(f"GET /users/alice         → {resp.status} {data}")

        # 404 Not Found
        async with session.get(f"{base}/users/nobody") as resp:
            assert resp.status == 404
            data = await resp.json()
            assert data == {
                "code": 40401,
                "message": "用户不存在",
                "data": None,
            }
            print(f"GET /users/nobody        → {resp.status} {data}")

        # 400 Bad Request
        async with session.post(f"{base}/users/alice/deactivate") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["code"] == 0
            print(f"POST /users/alice/deactivate (1st) → {resp.status} {data}")

        async with session.post(f"{base}/users/alice/deactivate") as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data == {
                "code": 40001,
                "message": "用户已停用，不能重复操作",
                "data": None,
            }
            print(f"POST /users/alice/deactivate (2nd) → {resp.status} {data}")

        # 422 Unprocessable Entity
        async with session.post(
            f"{base}/users",
            json={"username": "ab", "email": "a@b"},
        ) as resp:
            assert resp.status == 422
            data = await resp.json()
            assert data["code"] == 42200
            assert "username" in data["message"]
            print(f"POST /users (invalid)    → {resp.status} {data}")

        # 204 No Content
        async with session.delete(f"{base}/users/alice") as resp:
            assert resp.status == 204
            body = await resp.text()
            assert body == ""
            print(f"DELETE /users/alice      → {resp.status} body=<empty>")

    server.should_exit = True
    await task
    print("\n✓ 01_crud_status_codes 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
