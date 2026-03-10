"""
测试: 02_path_params 路由——路径参数校验
运行命令: uv run python examples/01_basics/02_path_params_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_path_params.py")
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
        async with session.get(f"{base}/users/42") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["user_id"] == 42
            print(f"GET /users/42      → {resp.status} {data}")

        # 违反 ge=1 约束
        async with session.get(f"{base}/users/0") as resp:
            assert resp.status == 422
            print(f"GET /users/0       → {resp.status} (422 校验失败)")

        # 类型错误
        async with session.get(f"{base}/users/abc") as resp:
            assert resp.status == 422
            print(f"GET /users/abc     → {resp.status} (422 类型错误)")

        # path 转换器
        async with session.get(f"{base}/files/docs/2024/report.pdf") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "docs/2024/report.pdf" in data["file_path"]
            print(f"GET /files/docs/.. → {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 02_path_params 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
