"""
测试: 02_async_and_rate_limit 路由——202 / 429 / 502 / 503 / 504
运行命令: uv run python examples/10_status_codes/02_async_and_rate_limit_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("02_async_and_rate_limit.py")
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

        # 202 Accepted
        async with session.post(f"{base}/reports") as resp:
            assert resp.status == 202
            data = await resp.json()
            task_id = data["data"]["task_id"]
            assert data["code"] == 0
            print(f"POST /reports            → {resp.status} {data}")

        await asyncio.sleep(0.3)

        async with session.get(f"{base}/reports/{task_id}") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["data"]["status"] == "completed"
            print(f"GET /reports/{{id}}       → {resp.status} {data}")

        # 429 Too Many Requests
        for index in range(4):
            async with session.get(f"{base}/limited") as resp:
                data = await resp.json()
                retry_after = resp.headers.get("Retry-After", "-")
                if index < 3:
                    assert resp.status == 200
                    assert data["code"] == 0
                else:
                    assert resp.status == 429
                    assert data["code"] == 42900
                    assert retry_after != "-"
                print(
                    f"GET /limited ({index + 1})      → {resp.status} "
                    f"Retry-After={retry_after} {data}"
                )

        # 502 Bad Gateway
        async with session.get(f"{base}/proxy/bad-gateway") as resp:
            assert resp.status == 502
            data = await resp.json()
            assert data["code"] == 50200
            print(f"GET /proxy/bad-gateway  → {resp.status} {data}")

        # 503 Service Unavailable
        async with session.get(f"{base}/proxy/unavailable") as resp:
            assert resp.status == 503
            data = await resp.json()
            assert data["code"] == 50300
            print(f"GET /proxy/unavailable  → {resp.status} {data}")

        # 504 Gateway Timeout
        async with session.get(f"{base}/proxy/timeout") as resp:
            assert resp.status == 504
            data = await resp.json()
            assert data["code"] == 50400
            print(f"GET /proxy/timeout      → {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 02_async_and_rate_limit 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
