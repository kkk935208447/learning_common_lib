"""
目标: 演示 response_model 过滤敏感字段（如 password_hash）
关键 API: APIRouter, response_model, BaseModel, HTTPException
Python 版本: 3.11+
运行命令: uv run python examples/02_request_response/02_response_model.py  (手动探索 /docs)
测试命令: uv run python examples/02_request_response/02_response_model_test.py
生产提醒: 永远不要在响应模型中暴露密码、token 等敏感字段
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: str
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    """响应模型：不包含密码。"""
    id: int
    username: str
    email: str


class UserInDB(BaseModel):
    id: int
    username: str
    email: str
    password_hash: str


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_db: dict[int, UserInDB] = {}
_next_id = 1

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["request_response"])


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate):
    """创建用户：response_model 自动过滤掉 password_hash。"""
    global _next_id
    db_user = UserInDB(
        id=_next_id,
        username=user.username,
        email=user.email,
        password_hash=f"hashed_{user.password}",
    )
    _db[_next_id] = db_user
    _next_id += 1
    # 用 model_dump 提取字段，再用 UserOut 过滤掉 password_hash
    out = UserOut(**db_user.model_dump())
    return JSONResponse(content=out.model_dump(), status_code=status.HTTP_201_CREATED)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int):
    if user_id not in _db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    out = UserOut(**_db[user_id].model_dump())
    return JSONResponse(content=out.model_dump())


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_response_model — 响应过滤")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
