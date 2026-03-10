"""
目标: 演示 Pydantic BaseModel 作为请求体、Field 校验、422 详细错误
关键 API: APIRouter, BaseModel, Field, HTTPException, status
Python 版本: 3.11+
运行命令: uv run python examples/02_request_response/01_request_body.py  (手动探索 /docs)
测试命令: uv run python examples/02_request_response/01_request_body_test.py
生产提醒: 请求体模型和数据库模型分开定义，避免内部字段泄露
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="物品名称")
    price: float = Field(gt=0, description="价格，必须大于 0")
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list)


class ItemOut(BaseModel):
    id: int
    name: str
    price: float
    description: str | None
    tags: list[str]


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_db: dict[int, dict] = {}
_next_id = 1

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["request_response"])


@router.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    """创建物品：Pydantic 自动校验请求体，不合法返回 422。"""
    global _next_id
    item_id = _next_id
    _next_id += 1
    record = {"id": item_id, **item.model_dump()}
    _db[item_id] = record
    return JSONResponse(content=record, status_code=status.HTTP_201_CREATED)


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_request_body — 请求体校验")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
