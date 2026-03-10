"""
测试: 03_cors_and_hooks 路由——CORS + lifespan
运行命令: uv run python examples/04_middleware_errors/03_cors_and_hooks_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_cors_and_hooks.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
create_app = _svc.create_app


async def main() -> None:
    app = create_app()

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        # 正常请求——lifespan 已初始化缓存
        async with session.get(f"{base}/config") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["cache"]["config"] == "loaded"
            print(f"GET /config → {resp.status} {data}")

        # CORS 预检请求（允许的源）
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        }
        async with session.options(f"{base}/config", headers=headers) as resp:
            cors = resp.headers.get("access-control-allow-origin", "无")
            assert cors == "http://localhost:3000"
            print(f"OPTIONS (localhost:3000) → {resp.status} allow-origin: {cors}")

        # CORS 预检请求（非允许源）
        headers = {
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        }
        async with session.options(f"{base}/config", headers=headers) as resp:
            cors = resp.headers.get("access-control-allow-origin", "无")
            assert cors == "无"
            print(f"OPTIONS (evil.com)      → {resp.status} allow-origin: {cors}")

    server.should_exit = True
    await task
    print("\n✓ 03_cors_and_hooks 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
