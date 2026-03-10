"""
测试: 02_async_test_client——演示 httpx AsyncClient + ASGITransport 异步测试
运行命令: uv run python examples/08_testing/02_async_test_client_test.py  (从 fastapi教程/ 目录)

本文件本身就是教学内容：展示如何用 AsyncClient 写异步测试。
"""

import asyncio
import importlib.util
from pathlib import Path

import httpx
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_async_test_client.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
get_db = _svc.get_db


async def test_create_and_list():
    """测试创建和列表。"""
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/notes", params={"title": "学习 FastAPI"})
        assert r.status_code == 201
        note_id = r.json()["id"]
        print(f"  ✓ 创建笔记 id={note_id}")

        r = await client.post("/notes", params={"title": "写测试"})
        assert r.status_code == 201
        print(f"  ✓ 创建笔记 id={r.json()['id']}")

        r = await client.get("/notes")
        assert r.status_code == 200
        assert len(r.json()) == 2
        print(f"  ✓ 列表返回 {len(r.json())} 条")


async def test_not_found():
    """测试 404。"""
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/notes/999")
        assert r.status_code == 404
        print("  ✓ 不存在的笔记返回 404")


async def test_with_dependency_override():
    """测试依赖覆盖。"""
    fake_db: dict[int, dict] = {1: {"id": 1, "title": "预置数据"}}

    async def override_db() -> dict:
        return fake_db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = override_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/notes")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["title"] == "预置数据"
        print("  ✓ 依赖覆盖生效")


async def main() -> None:
    print("--- 异步 AsyncClient 测试 ---")
    # 重置模块状态
    _svc._db.clear()
    _svc._next_id = 0

    await test_create_and_list()
    await test_not_found()
    await test_with_dependency_override()
    print("\n所有异步测试通过！")


if __name__ == "__main__":
    asyncio.run(main())
