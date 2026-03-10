"""
目标: 演示查询参数、可选参数、Query() 约束和分页模式
关键 API: APIRouter, Query, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/03_query_params.py  (手动探索 /docs)
测试命令: uv run python examples/01_basics/03_query_params_test.py
生产提醒: 分页参数建议封装为 Depends 依赖（见 03_dependency_injection）
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class ItemOut(BaseModel):
    id: int
    name: str


class PaginatedItems(BaseModel):
    total: int
    skip: int
    limit: int
    q: str | None
    data: list[ItemOut]


# ---------------------------------------------------------------------------
# 模拟数据
# ---------------------------------------------------------------------------

ITEMS = [ItemOut(id=i, name=f"item_{i}") for i in range(50)]

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["basics"])


@router.get("/items", response_model=PaginatedItems)
async def list_items(
    skip: int = Query(default=0, ge=0, description="跳过条数"),
    limit: int = Query(default=10, ge=1, le=100, description="每页条数"),
    q: str | None = Query(default=None, max_length=50, description="搜索关键词"),
):
    """查询参数 + 分页：skip/limit 控制分页，q 可选搜索。"""
    results = ITEMS[skip : skip + limit]
    if q:
        results = [item for item in results if q in item.name]
    return JSONResponse(
        content={
            "total": len(ITEMS),
            "skip": skip,
            "limit": limit,
            "q": q,
            "data": [item.model_dump() for item in results],
        }
    )


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="03_query_params — 查询参数")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
