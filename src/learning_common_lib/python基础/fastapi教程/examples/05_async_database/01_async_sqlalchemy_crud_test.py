"""
测试: 01_async_sqlalchemy_crud 路由——文件型 SQLite CRUD
运行命令: uv run python examples/05_async_database/01_async_sqlalchemy_crud_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_async_sqlalchemy_crud.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)

reset_database = _svc.reset_database
get_database_file = _svc.get_database_file
create_app = _svc.create_app


async def start_server() -> tuple[uvicorn.Server, asyncio.Task, str]:
    app = create_app()

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, f"http://127.0.0.1:{port}"


async def stop_server(server: uvicorn.Server, task: asyncio.Task) -> None:
    server.should_exit = True
    await task


async def main() -> None:
    # 每次测试先清空数据库，但仍然使用文件型 SQLite。
    await reset_database()
    assert get_database_file().exists()

    # 第一次启动服务：写入数据
    server, task, base = await start_server()

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base}/todos", json={"title": "学习 FastAPI"}) as resp:
            assert resp.status == 201
            data = await resp.json()
            first_todo_id = data["id"]
            print(f"POST /todos       → {resp.status} {data}")

        async with session.post(f"{base}/todos", json={"title": "写单元测试"}) as resp:
            assert resp.status == 201
            print(f"POST /todos       → {resp.status} {await resp.json()}")

        async with session.get(f"{base}/todos") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 2
            print(f"GET /todos        → {resp.status} count={len(data)}")

    await stop_server(server, task)

    # 第二次启动服务：不重置数据库，验证文件型 SQLite 的持久化效果。
    server, task, base = await start_server()

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/todos") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 2
            print(f"GET /todos (restart) → {resp.status} count={len(data)}")

        async with session.patch(f"{base}/todos/{first_todo_id}", json={"done": True}) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["done"] is True
            print(f"PATCH /todos/{first_todo_id} → {resp.status} done={data['done']}")

        async with session.delete(f"{base}/todos/{first_todo_id}") as resp:
            assert resp.status == 204
            print(f"DELETE /todos/{first_todo_id} → {resp.status}")

        async with session.get(f"{base}/todos/{first_todo_id}") as resp:
            assert resp.status == 404
            print(f"GET /todos/{first_todo_id} → {resp.status} (404)")

    await stop_server(server, task)
    print(f"\n✓ 01_async_sqlalchemy_crud 所有测试通过，数据库文件位于: {get_database_file()}")


if __name__ == "__main__":
    asyncio.run(main())
