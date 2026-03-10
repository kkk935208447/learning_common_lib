"""
测试: 03_nested_models 路由——嵌套模型与 validator
运行命令: uv run python examples/02_request_response/03_nested_models_test.py  (从 fastapi教程/ 目录)
"""

import asyncio
import importlib.util
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("03_nested_models.py")
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
        # 合法嵌套请求
        async with session.post(f"{base}/orders", json={
            "customer_name": "张三",
            "shipping_address": {"city": "北京", "street": "长安街1号", "zipcode": "100000"},
            "items": [
                {"product": "键盘", "quantity": 2, "unit_price": 299.0},
                {"product": "鼠标", "quantity": 1, "unit_price": 99.5},
            ],
        }) as resp:
            assert resp.status == 201
            data = await resp.json()
            assert data["customer"] == "张三"
            assert data["total"] == 697.5
            print(f"POST /orders (valid)    → {resp.status} {data}")

        # 邮编格式错误
        async with session.post(f"{base}/orders", json={
            "customer_name": "李四",
            "shipping_address": {"city": "上海", "street": "南京路", "zipcode": "ABC"},
            "items": [{"product": "书", "quantity": 1, "unit_price": 50}],
        }) as resp:
            assert resp.status == 422
            print(f"POST /orders (bad zip)  → {resp.status} (422)")

        # 空 items 列表
        async with session.post(f"{base}/orders", json={
            "customer_name": "王五",
            "shipping_address": {"city": "广州", "street": "天河路", "zipcode": "510000"},
            "items": [],
        }) as resp:
            assert resp.status == 422
            print(f"POST /orders (no items) → {resp.status} (422)")

    server.should_exit = True
    await task
    print("\n✓ 03_nested_models 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
