"""
测试: 01_background_tasks 路由——后台任务执行
运行命令: uv run python examples/06_background_streaming/01_background_tasks_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_background_tasks.py")
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
        # 创建订单（立即返回）
        async with session.post(f"{base}/orders") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "created"
            print(f"POST /orders → {resp.status} {data}")

        # 等待后台任务完成
        await asyncio.sleep(0.3)

        # 查看后台任务日志
        async with session.get(f"{base}/task-log") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert len(data["log"]) >= 2
            print(f"GET /task-log → {resp.status} count={len(data['log'])}")
            for entry in data["log"]:
                print(f"  - {entry}")

    server.should_exit = True
    await task
    print("\n✓ 01_background_tasks 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
