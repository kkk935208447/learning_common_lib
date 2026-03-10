"""
目标: 演示 JWT Bearer 认证——用 stdlib hmac 签发和验证 JWT（不引入 PyJWT）
关键 API: APIRouter, hmac, hashlib, base64, OAuth2PasswordBearer
Python 版本: 3.11+
运行命令: uv run python examples/07_auth/02_jwt_bearer.py  (手动探索 /docs)
测试命令: uv run python examples/07_auth/02_jwt_bearer_test.py
生产提醒: 生产环境建议用 PyJWT/python-jose，本示例用 stdlib 演示 JWT 原理
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

SECRET_KEY = "my-secret-key-for-demo-only"
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 300

FAKE_USERS = {
    "alice": {"username": "alice", "password": "alice123", "role": "admin"},
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# ---------------------------------------------------------------------------
# 简易 JWT 实现（仅用于教学，生产用 PyJWT）
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def create_jwt(payload: dict) -> str:
    header = {"alg": ALGORITHM, "typ": "JWT"}
    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    signature = hmac.new(SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    s = _b64url_encode(signature)
    return f"{h}.{p}.{s}"


def decode_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("无效 JWT 格式")
    h, p, s = parts
    expected = hmac.new(SECRET_KEY.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    actual = _b64url_decode(s)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("签名验证失败")
    payload = json.loads(_b64url_decode(p))
    if payload.get("exp", 0) < time.time():
        raise ValueError("token 已过期")
    return payload


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
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "exp": time.time() + TOKEN_EXPIRE_SECONDS,
    }
    return JSONResponse(
        content={"access_token": create_jwt(payload), "token_type": "bearer"}
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = decode_jwt(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        )
    return {"username": payload["sub"], "role": payload["role"]}


@router.get("/me")
async def read_me(user: dict = Depends(get_current_user)):
    return JSONResponse(content=user)


@router.get("/admin")
async def admin_only(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要 admin 角色"
        )
    return JSONResponse(content={"message": f"欢迎管理员 {user['username']}"})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_jwt_bearer — JWT 认证")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
