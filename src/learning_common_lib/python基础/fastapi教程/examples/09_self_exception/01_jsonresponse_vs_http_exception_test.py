"""
测试: 01_jsonresponse_vs_http_exception 路由——比较 JSONResponse 与 HTTPException
运行命令: uv run python examples/09_self_exception/01_jsonresponse_vs_http_exception_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_jsonresponse_vs_http_exception.py")
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
        # JSONResponse: 客户端拿到的 body 完全由后端自己决定
        async with session.get(f"{base}/test/jsonresponse-error") as resp:
            assert resp.status == 400
            data = await resp.json()
            assert data == {
                "code": 1001,
                "message": "用户名已存在",
                "data": None,
            }
            print(f"GET /test/jsonresponse-error → {resp.status} {data}")

        # HTTPException: 客户端拿到 FastAPI 默认的 detail 结构
        async with session.get(f"{base}/test/http-exception-error/999") as resp:
            assert resp.status == 404
            data = await resp.json()
            assert data == {"detail": "找不到该用户"}
            print(f"GET /test/http-exception-error/999 → {resp.status} {data}")

        # 正常成功路径
        async with session.get(f"{base}/test/http-exception-error/1") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["code"] == 0
            assert data["data"]["id"] == 1
            print(f"GET /test/http-exception-error/1 → {resp.status} {data}")

    server.should_exit = True
    await task
    print("\n✓ 01_jsonresponse_vs_http_exception 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
