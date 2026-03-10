"""
目标: 用最小代码讲清 return JSONResponse 和 raise HTTPException 的区别
关键 API: APIRouter, JSONResponse, HTTPException, status
Python 版本: 3.11+
运行命令: uv run python examples/09_self_exception/01_jsonresponse_vs_http_exception.py
测试命令: uv run python examples/09_self_exception/01_jsonresponse_vs_http_exception_test.py
生产提醒: JSONResponse 适合“我想自己决定返回什么”；HTTPException 适合“我想立刻中断并交给框架处理”
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 这个示例只回答一个问题：
#
# 1. return JSONResponse
#    代表“我自己手动构造响应内容和状态码”
#
# 2. raise HTTPException
#    代表“这里出错了，请立刻中断请求，并交给 FastAPI 生成错误响应”
# ---------------------------------------------------------------------------

router = APIRouter(tags=["self_exception"])


def get_user_or_raise(user_id: int) -> dict:
    """
    模拟一个深层函数。

    如果用户不存在，直接 raise HTTPException。
    这说明 HTTPException 不一定非要在路由函数里抛，
    也可以在 service / helper / depends 里抛。
    """
    if user_id != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到该用户",
        )
    return {"id": 1, "name": "Alice"}


@router.get("/test/jsonresponse-error")
async def test_jsonresponse_error():
    """
    手动返回 JSONResponse。

    常见场景:
    - 公司要求固定返回体结构
    - 需要自定义 headers / cookies
    - 需要返回和 FastAPI 默认风格不一样的 JSON
    """
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": 1001,
            "message": "用户名已存在",
            "data": None,
        },
    )


@router.get("/test/http-exception-error/{user_id}")
async def test_http_exception_error(user_id: int):
    """
    这里不自己 return 错误，而是交给 helper 去 raise。

    如果 helper 抛出 HTTPException，后续代码不会继续执行。
    """
    user = get_user_or_raise(user_id)
    return {
        "code": 0,
        "message": "查询成功",
        "data": user,
    }


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="01_jsonresponse_vs_http_exception")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
