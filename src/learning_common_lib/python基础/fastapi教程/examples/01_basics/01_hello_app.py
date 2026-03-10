"""
目标: 演示最小 FastAPI 应用——APIRouter 定义路由、返回 JSON
关键 API: APIRouter, JSONResponse, Pydantic BaseModel
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/01_hello_app.py  (手动探索 /docs)
测试命令: uv run python examples/01_basics/01_hello_app_test.py
生产提醒: 生产环境用 gunicorn + uvicorn worker，不要直接 uvicorn.run()
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic 响应模型
# ---------------------------------------------------------------------------


class HelloResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["basics"])


@router.get("/", response_model=HelloResponse)
async def root():
    """根路由：返回欢迎消息。"""
    return JSONResponse(content={"message": "Hello, FastAPI!"})


@router.get("/hello/{name}", response_model=HelloResponse)
async def hello(name: str):
    """动态路由：根据路径参数返回个性化问候。"""
    return JSONResponse(content={"message": f"Hello, {name}!"})


# ---------------------------------------------------------------------------
# 手动探索: python 01_hello_app.py → 浏览器访问 http://127.0.0.1:8000/docs
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_hello_app — 最小应用")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
