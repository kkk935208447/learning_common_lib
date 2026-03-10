"""
测试: 02_pydantic_validation_422 路由——默认 422 与公司统一 400 的对比
运行命令: uv run python examples/09_self_exception/02_pydantic_validation_422_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_pydantic_validation_422.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
register_company_validation_handler = _svc.register_company_validation_handler


async def start_server(app: FastAPI) -> tuple[uvicorn.Server, asyncio.Task, str]:
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
    # ------------------------------------------------------------------
    # 场景 1: 不注册自定义异常处理器，直接看 FastAPI 默认 422
    # ------------------------------------------------------------------
    default_app = FastAPI()
    default_app.include_router(router)
    server, task, base = await start_server(default_app)

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base}/test/reset") as resp:
            assert resp.status == 204

        async with session.post(
            f"{base}/test/users",
            json={
                "username": "alice",
                "age": "not-an-int",
                "email": "alice@example.com",
            },
        ) as resp:
            assert resp.status == 422
            data = await resp.json()
            first_error = data["detail"][0]
            assert first_error["loc"][-1] == "age"
            print(f"POST /test/users (default 422) → {resp.status} {data}")

        async with session.get(f"{base}/test/metrics") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["service_call_count"] == 0
            print(f"GET /test/metrics → {resp.status} {data}")

    await stop_server(server, task)

    # ------------------------------------------------------------------
    # 场景 2: 注册公司统一校验处理器，把 422 改造成 400 + 统一 JSON
    # ------------------------------------------------------------------
    company_app = FastAPI()
    register_company_validation_handler(company_app)
    company_app.include_router(router)
    server, task, base = await start_server(company_app)

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base}/test/reset") as resp:
            assert resp.status == 204

        async with session.post(
            f"{base}/test/users",
            json={
                "username": "alice",
                "age": "not-an-int",
                "email": "alice@example.com",
            },
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data == {
                "code": 4001,
                "message": "参数 'age' 错误: Input should be a valid integer, unable to parse string as an integer",
                "data": None,
            }
            print(f"POST /test/users (company 400) → {resp.status} {data}")

        async with session.get(f"{base}/test/metrics") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["service_call_count"] == 0
            print(f"GET /test/metrics → {resp.status} {data}")

    await stop_server(server, task)
    print("\n✓ 02_pydantic_validation_422 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
