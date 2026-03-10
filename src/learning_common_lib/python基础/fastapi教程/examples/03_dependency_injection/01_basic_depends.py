"""
目标: 演示 Depends 基础用法——将分页参数提取为可复用依赖
关键 API: APIRouter, Depends, Query, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/03_dependency_injection/01_basic_depends.py  (手动探索 /docs)
测试命令: uv run python examples/03_dependency_injection/01_basic_depends_test.py
生产提醒: 公共参数（分页、排序、过滤）都应封装为 Depends，保持端点函数简洁
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 分页依赖——可在多个端点间复用
# ---------------------------------------------------------------------------


class PaginationParams:
    """分页参数依赖类。"""

    def __init__(
        self,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=10, ge=1, le=100),
    ):
        self.skip = skip
        self.limit = limit


# ---------------------------------------------------------------------------
# 模拟数据
# ---------------------------------------------------------------------------

ITEMS = [{"id": i, "name": f"item_{i}"} for i in range(30)]
USERS = [{"id": i, "username": f"user_{i}"} for i in range(20)]

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["dependency_injection"])


@router.get("/items")
async def list_items(pagination: PaginationParams = Depends()):
    """两个端点共享同一分页依赖。"""
    data = ITEMS[pagination.skip : pagination.skip + pagination.limit]
    return JSONResponse(content={"total": len(ITEMS), "data": data})


@router.get("/users")
async def list_users(pagination: PaginationParams = Depends()):
    data = USERS[pagination.skip : pagination.skip + pagination.limit]
    return JSONResponse(content={"total": len(USERS), "data": data})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_basic_depends — Depends 基础")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
