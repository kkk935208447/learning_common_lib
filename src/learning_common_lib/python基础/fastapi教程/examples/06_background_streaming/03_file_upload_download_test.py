"""
测试: 03_file_upload_download 路由——文件上传下载
运行命令: uv run python examples/06_background_streaming/03_file_upload_download_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_file_upload_download.py")
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

    test_content = b"Hello, FastAPI file upload!"

    async with aiohttp.ClientSession() as session:
        # 上传文件
        form = aiohttp.FormData()
        form.add_field("file", test_content, filename="test.txt", content_type="text/plain")
        async with session.post(f"{base}/upload", data=form) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["filename"] == "test.txt"
            assert data["size"] == len(test_content)
            print(f"POST /upload   → {resp.status} {data}")

        # 列出文件
        async with session.get(f"{base}/files") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "test.txt" in data["files"]
            print(f"GET /files     → {resp.status} {data}")

        # 下载文件
        async with session.get(f"{base}/download/test.txt") as resp:
            assert resp.status == 200
            content = await resp.read()
            assert content == test_content
            print(f"GET /download  → {resp.status} size={len(content)}")
            print("  ✓ 下载内容与上传一致")

        # 下载不存在的文件
        async with session.get(f"{base}/download/nope.txt") as resp:
            assert resp.status == 404
            print(f"GET /download  → {resp.status} (404)")

    server.should_exit = True
    await task
    print("\n✓ 03_file_upload_download 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
