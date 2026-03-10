"""
目标: 演示 Starlette TestClient 同步测试 FastAPI 应用
关键 API: APIRouter, TestClient, dependency_overrides
Python 版本: 3.11+
运行命令: uv run python examples/08_testing/01_sync_test_client.py  (手动探索 /docs)
测试命令: uv run python examples/08_testing/01_sync_test_client_test.py
生产提醒: TestClient 内部用 anyio 运行异步代码，适合简单测试；复杂场景用 async 测试
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 依赖
# ---------------------------------------------------------------------------


def get_settings() -> dict:
    return {"env": "production", "debug": False}


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class Item(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["testing"])


@router.get("/settings")
async def read_settings(settings: dict = Depends(get_settings)):
    return JSONResponse(content=settings)


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(item: Item):
    return JSONResponse(
        content={"id": 1, **item.model_dump()},
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )
    return JSONResponse(content={"id": 1, "name": "Widget", "price": 9.99})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_sync_test_client — 同步测试")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
