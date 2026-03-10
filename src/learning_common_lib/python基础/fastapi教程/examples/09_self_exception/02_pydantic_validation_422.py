"""
目标: 演示 Pydantic 默认 422，以及如何改造成公司统一的 400 JSON 返回
关键 API: APIRouter, BaseModel, Field, RequestValidationError, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/09_self_exception/02_pydantic_validation_422.py
测试命令: uv run python examples/09_self_exception/02_pydantic_validation_422_test.py
生产提醒: 默认 422 很详细，适合调试；但很多公司会拦截成统一的 400 或 200
"""

from fastapi import APIRouter, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 这里用计数器观察一个非常重要的事实：
# 如果请求参数没通过 Pydantic 校验，路由函数根本不会执行。
# ---------------------------------------------------------------------------

_service_call_count = 0


class UserCreate(BaseModel):
    username: str
    age: int
    email: str


router = APIRouter(tags=["self_exception"])


def register_company_validation_handler(app) -> None:
    """
    模拟很多国内公司的统一错误包装风格。

    默认 422 很详细，但前端往往希望拿到统一结构，方便全局拦截：
    {"code": 4001, "message": "...", "data": null}
    """

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_error = exc.errors()[0]
        field = first_error.get("loc", ["body"])[-1]
        message = first_error.get("msg", "参数错误")

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "code": 4001,
                "message": f"参数 '{field}' 错误: {message}",
                "data": None,
            },
        )


@router.post("/test/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_state():
    global _service_call_count
    _service_call_count = 0


@router.get("/test/metrics")
async def read_metrics():
    return {"service_call_count": _service_call_count}


@router.post("/test/users")
async def create_user(user: UserCreate):
    """
    只要请求能走到这里，就说明 Pydantic 校验已经通过了。
    """
    global _service_call_count
    _service_call_count += 1
    return {
        "code": 0,
        "message": "用户创建成功",
        "data": user.model_dump(),
    }


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="02_pydantic_validation_422")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
