"""
目标: 演示 OAuth2 密码模式——用户名密码登录获取 token
关键 API: APIRouter, OAuth2PasswordBearer, OAuth2PasswordRequestForm, Depends
Python 版本: 3.11+
运行命令: uv run python examples/07_auth/01_oauth2_password.py  (手动探索 /docs)
测试命令: uv run python examples/07_auth/01_oauth2_password_test.py
生产提醒: 密码必须哈希存储（bcrypt/argon2），示例中的明文比较仅用于教学
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

# ---------------------------------------------------------------------------
# 模拟用户数据库（生产环境密码必须哈希）
# ---------------------------------------------------------------------------

FAKE_USERS = {
    "alice": {"username": "alice", "password": "alice123", "role": "admin"},
    "bob": {"username": "bob", "password": "bob456", "role": "viewer"},
}

TOKENS: dict[str, str] = {}  # token → username

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["auth"])


@router.post("/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    user = FAKE_USERS.get(form.username)
    if not user or user["password"] != form.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    token = f"fake_token_{form.username}"
    TOKENS[token] = form.username
    return JSONResponse(content={"access_token": token, "token_type": "bearer"})


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    username = TOKENS.get(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效 token"
        )
    return FAKE_USERS[username]


@router.get("/me")
async def read_me(user: dict = Depends(get_current_user)):
    return JSONResponse(content={"username": user["username"], "role": user["role"]})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_oauth2_password — OAuth2 密码模式")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
