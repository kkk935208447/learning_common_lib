"""
测试: 02_repository_pattern 路由——文件型 SQLite + Repository 模式
运行命令: uv run python examples/05_async_database/02_repository_pattern_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_repository_pattern.py")
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
    await reset_database()
    assert get_database_file().exists()

    # 第一次启动服务：写入图书数据。
    server, task, base = await start_server()

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base}/books",
            json={"title": "Python Cookbook", "author": "David Beazley"},
        ) as resp:
            assert resp.status == 201
            first_book = await resp.json()
            print(f"POST /books   → {resp.status} {first_book}")

        async with session.post(
            f"{base}/books",
            json={"title": "Fluent Python", "author": "Luciano Ramalho"},
        ) as resp:
            assert resp.status == 201
            print(f"POST /books   → {resp.status} {await resp.json()}")

    await stop_server(server, task)

    # 第二次启动服务：验证数据库文件持久化。
    server, task, base = await start_server()

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/books") as resp:
            assert resp.status == 200
            books = await resp.json()
            assert len(books) == 2
            print(f"GET /books (restart) → {resp.status} count={len(books)}")

        async with session.get(f"{base}/books/{first_book['id']}") as resp:
            assert resp.status == 200
            book = await resp.json()
            assert book["title"] == "Python Cookbook"
            print(f"GET /books/{first_book['id']} → {resp.status} {book}")

        async with session.delete(f"{base}/books/{first_book['id']}") as resp:
            assert resp.status == 204
            print(f"DELETE /books/{first_book['id']} → {resp.status}")

        async with session.get(f"{base}/books/{first_book['id']}") as resp:
            assert resp.status == 404
            print(f"GET /books/{first_book['id']} → {resp.status} (404)")

    await stop_server(server, task)
    print(f"\n✓ 02_repository_pattern 所有测试通过，数据库文件位于: {get_database_file()}")


if __name__ == "__main__":
    asyncio.run(main())
