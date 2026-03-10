"""
目标: 演示自定义异常类 + exception_handler 统一错误响应格式
关键 API: APIRouter, HTTPException, @app.exception_handler, RequestValidationError
Python 版本: 3.11+
运行命令: uv run python examples/04_middleware_errors/01_exception_handlers.py  (手动探索 /docs)
测试命令: uv run python examples/04_middleware_errors/01_exception_handlers_test.py
生产提醒: 统一错误格式让前端只需处理一种错误结构，大幅降低联调成本
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class AppError(Exception):
    """业务异常基类。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: int | str):
        super().__init__(
            code="NOT_FOUND",
            message=f"{resource} {resource_id} 不存在",
            status_code=404,
        )


# ---------------------------------------------------------------------------
# 统一错误响应模型
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: list | None = None


# ---------------------------------------------------------------------------
# 注册异常处理器的函数（测试文件调用）
# ---------------------------------------------------------------------------


def register_exception_handlers(app):
    """将自定义异常处理器注册到 app。"""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(code=exc.code, message=exc.message).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                code="VALIDATION_ERROR",
                message="请求参数校验失败",
                detail=exc.errors(),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["middleware_errors"])


class ItemCreate(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)


@router.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id != 1:
        raise NotFoundError("Item", item_id)
    return JSONResponse(content={"id": 1, "name": "Widget"})


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    return JSONResponse(
        content={"id": 2, **item.model_dump()},
        status_code=status.HTTP_201_CREATED,
    )


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_exception_handlers — 统一错误格式")
    register_exception_handlers(app)
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
