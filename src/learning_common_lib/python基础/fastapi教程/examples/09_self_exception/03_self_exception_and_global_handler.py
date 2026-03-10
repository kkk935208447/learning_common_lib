"""
目标: 用最小代码演示 BusinessException 和 Exception 全局兜底
关键 API: APIRouter, JSONResponse, exception_handler
Python 版本: 3.11+
运行命令: uv run python examples/09_self_exception/03_self_exception_and_global_handler.py
测试命令: uv run python examples/09_self_exception/03_self_exception_and_global_handler_test.py
生产提醒: 业务异常要友好返回给前端；未知异常要记录完整堆栈，但不能把内部细节暴露给客户端
"""

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("fastapi.self_exception")
router = APIRouter(tags=["self_exception"])


class BusinessException(Exception):
    """
    业务可控的异常。

    比如:
    - VIP 已过期
    - 余额不足
    - 库存不够
    - 权限不足
    """

    def __init__(self, err_code: int, err_msg: str):
        self.err_code = err_code
        self.err_msg = err_msg


def register_exception_handlers(app) -> None:
    """
    注册全局异常处理器。

    这是企业项目里最常见的套路：
    1. 业务异常 -> 统一包装成前端可直接消费的 JSON
    2. 未知异常 -> 记录完整堆栈，返回通用 500
    """

    @app.exception_handler(BusinessException)
    async def business_exception_handler(
        request: Request, exc: BusinessException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "code": exc.err_code,
                "message": exc.err_msg,
                "data": None,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 生产环境必须把真实错误打到日志里，排查问题靠它。
        logger.error(
            "系统发生未知错误: path=%s error=%s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": 5000,
                "message": "服务器开小差了，请稍后再试 (Internal Server Error)",
                "data": None,
            },
        )


@router.get("/test/success")
async def test_success():
    return {
        "code": 0,
        "message": "请求成功",
        "data": {"user": "alice", "vip": True},
    }


@router.get("/test/business-error")
async def test_business_error():
    """
    主动抛业务异常。

    客户端应该拿到:
    HTTP 200
    {"code": 40001, "message": "...", "data": null}
    """
    raise BusinessException(
        err_code=40001,
        err_msg="您的VIP已过期，无法查看此内容",
    )


@router.get("/test/system-bug")
async def test_system_bug():
    """
    模拟未知代码 Bug。

    客户端只能看到统一 500。
    真正的 ZeroDivisionError 堆栈会打印到服务端日志。
    """
    value = 1 / 0
    return {"value": value}


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    app = FastAPI(title="03_self_exception_and_global_handler")
    register_exception_handlers(app)
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
