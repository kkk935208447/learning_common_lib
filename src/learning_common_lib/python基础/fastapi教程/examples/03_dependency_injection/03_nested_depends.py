"""
目标: 演示依赖链——auth → user → permission 三层嵌套依赖
关键 API: APIRouter, Depends, Header, HTTPException, status
Python 版本: 3.11+
运行命令: uv run python examples/03_dependency_injection/03_nested_depends.py  (手动探索 /docs)
测试命令: uv run python examples/03_dependency_injection/03_nested_depends_test.py
生产提醒: 依赖链天然形成中间件管道，比装饰器嵌套更清晰、更易测试
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 模拟用户数据库
# ---------------------------------------------------------------------------

USERS_DB = {
    "token_admin": {"username": "admin", "role": "admin"},
    "token_viewer": {"username": "viewer", "role": "viewer"},
}


# --- 第一层：认证 ---
async def verify_token(authorization: str = Header()) -> str:
    """从 Header 提取 token 并验证。"""
    token = authorization.replace("Bearer ", "")
    if token not in USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token"
        )
    return token


# --- 第二层：获取用户（依赖第一层）---
async def get_current_user(token: str = Depends(verify_token)) -> dict:
    return USERS_DB[token]


# --- 第三层：权限检查（依赖第二层）---
def require_role(role: str):
    """工厂函数：生成角色检查依赖。"""
    async def check_role(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {role} 角色",
            )
        return user
    return check_role


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["dependency_injection"])


@router.get("/profile")
async def profile(user: dict = Depends(get_current_user)):
    return JSONResponse(content={"user": user})


@router.delete("/admin/cleanup")
async def admin_cleanup(user: dict = Depends(require_role("admin"))):
    return JSONResponse(
        content={"message": f"{user['username']} 执行了清理操作"}
    )


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="03_nested_depends — 依赖链")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
