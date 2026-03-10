"""
目标: 演示路径参数的类型注解、约束校验和 422 自动错误响应
关键 API: APIRouter, Path, HTTPException, status
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/02_path_params.py  (手动探索 /docs)
测试命令: uv run python examples/01_basics/02_path_params_test.py
生产提醒: Path() 约束在文档中自动体现，善用 ge/le/regex 减少手动校验
"""

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    user_id: int
    name: str


class FileResponse(BaseModel):
    file_path: str


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["basics"])


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int = Path(ge=1, description="用户 ID，必须 >= 1")):
    """路径参数类型注解 + ge 约束：user_id 必须为正整数。"""
    return JSONResponse(content={"user_id": user_id, "name": f"user_{user_id}"})


@router.get("/files/{file_path:path}", response_model=FileResponse)
async def get_file(file_path: str):
    """path 转换器：匹配包含 / 的路径，如 docs/2024/report.pdf。"""
    return JSONResponse(content={"file_path": file_path})


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_path_params — 路径参数")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
