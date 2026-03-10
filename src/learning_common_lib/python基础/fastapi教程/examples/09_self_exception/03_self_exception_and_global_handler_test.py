"""
测试: 03_self_exception_and_global_handler 路由——BusinessException 与全局 500 兜底
运行命令: uv run python examples/09_self_exception/03_self_exception_and_global_handler_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_self_exception_and_global_handler.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
register_exception_handlers = _svc.register_exception_handlers


async def main() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/test/success") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["code"] == 0
            print(f"GET /test/success → {resp.status} {data}")

        # 业务异常: 返回 HTTP 200 + 统一业务码
        async with session.get(f"{base}/test/business-error") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data == {
                "code": 40001,
                "message": "您的VIP已过期，无法查看此内容",
                "data": None,
            }
            print(f"GET /test/business-error → {resp.status} {data}")

        # 未知异常: 返回 HTTP 500 + 通用文案，敏感错误不能暴露给客户端
        async with session.get(f"{base}/test/system-bug") as resp:
            assert resp.status == 500
            body_text = await resp.text()
            assert "division by zero" not in body_text
            data = await resp.json()
            assert data == {
                "code": 5000,
                "message": "服务器开小差了，请稍后再试 (Internal Server Error)",
                "data": None,
            }
            print(f"GET /test/system-bug → {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 03_self_exception_and_global_handler 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
