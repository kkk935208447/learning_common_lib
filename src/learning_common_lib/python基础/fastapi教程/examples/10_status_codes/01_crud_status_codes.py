"""
目标: 用最小代码讲清 201 / 204 / 400 / 404 / 409 / 422 的使用场景
关键 API: APIRouter, HTTPException, RequestValidationError, JSONResponse, Response
Python 版本: 3.11+
运行命令: uv run python examples/10_status_codes/01_crud_status_codes.py
测试命令: uv run python examples/10_status_codes/01_crud_status_codes_test.py
生产提醒: 这一章既要讲状态码，也要保持企业项目常见的统一 JSON 返回结构
"""

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 这是一份“教程版”状态码示例。
# 重点不是抽象设计，而是把常见状态码的边界讲清楚。
# ---------------------------------------------------------------------------

router = APIRouter(tags=["status_codes"])
_users: dict[str, dict] = {}


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    email: str = Field(min_length=5, max_length=50)


def success(message: str, data):
    """统一成功返回体。"""
    return {
        "code": 0,
        "message": message,
        "data": data,
    }


def api_error(status_code: int, code: int, message: str) -> HTTPException:
    """
    统一构造 HTTPException。

    detail 直接放成字典，这样异常处理器就能把它原样返回给客户端。
    """
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "data": None,
        },
    )


def register_status_exception_handlers(app) -> None:
    """
    为这一章注册统一异常处理器。

    这样可以同时满足两点：
    1. HTTP 状态码表达语义
    2. 响应体结构对前端稳定
    """

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code * 100,
                "message": str(exc.detail),
                "data": None,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_error = exc.errors()[0]
        field = first_error.get("loc", ["body"])[-1]
        message = first_error.get("msg", "参数校验失败")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": 42200,
                "message": f"参数 '{field}' 校验失败: {message}",
                "data": None,
            },
        )


@router.post("/test/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_state():
    """测试前清空内存状态。"""
    _users.clear()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate):
    """
    201 Created:
    资源创建成功。

    409 Conflict:
    比如用户名重复、订单重复提交、唯一键冲突。
    """
    if body.username in _users:

        # 注意：这里错误必须用 raise，不能 return， raise 会直接中断请求处理流程，不会执行后续代码
        raise api_error(
            status_code=status.HTTP_409_CONFLICT,
            code=40901,
            message="用户名已存在",
        )

    _users[body.username] = {
        "username": body.username,
        "email": body.email,
        "deactivated": False,
    }
    return success(
        message="用户创建成功",
        data={"username": body.username, "email": body.email},
    )


@router.get("/users/{username}")
async def get_user(username: str):
    """
    200 OK:
    资源查询成功。

    404 Not Found:
    路径是对的，但资源不存在。
    """
    user = _users.get(username)
    if not user:
        raise api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code=40401,
            message="用户不存在",
        )

    return success(
        message="查询成功",
        data={"username": user["username"], "email": user["email"]},
    )


@router.post("/users/{username}/deactivate")
async def deactivate_user(username: str):
    """
    400 Bad Request:
    请求格式没问题，但业务规则不允许。

    比如:
    - 用户已经停用，不能重复停用
    - 余额不足
    - 优惠券已经失效
    """
    user = _users.get(username)
    if not user:
        raise api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code=40401,
            message="用户不存在",
        )

    if user["deactivated"]:
        raise api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=40001,
            message="用户已停用，不能重复操作",
        )

    user["deactivated"] = True
    return success(
        message="用户已停用",
        data={"username": username, "deactivated": True},
    )


@router.delete("/users/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(username: str):
    """
    204 No Content:
    删除成功，但不需要返回任何 body。

    这是少数“成功但没有统一 JSON 返回体”的场景。
    """
    if username not in _users:
        raise api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code=40401,
            message="用户不存在",
        )

    del _users[username]
    return Response(status_code=status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_crud_status_codes")
    register_status_exception_handlers(app)
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
