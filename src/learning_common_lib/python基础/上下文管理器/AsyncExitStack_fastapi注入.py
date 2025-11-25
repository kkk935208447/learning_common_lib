# ==================== 示例 2: FastAPI 依赖注入中使用 ====================

from fastapi import FastAPI, Depends, APIRouter
from contextlib import AsyncExitStack
import asyncio
from typing import TypedDict


app = FastAPI()


class AsyncDatabase:
    """模拟异步数据库连接"""
    def __init__(self, name: str):
        self.name = name
        self.connected = False
    
    # 这是异步上下文进入方法，当使用 async with 进入上下文时调用
    async def __aenter__(self):
        await asyncio.sleep(0.1)  # 模拟连接延迟
        self.connected = True
        print(f"{self.name} 数据库已连接")
        return self
    
    # 这是异步上下文退出方法，当使用 async with 退出上下文时调用
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await asyncio.sleep(0.1)  # 模拟关闭延迟
        self.connected = False
        print(f"{self.name} 数据库已断开")
    
    async def query(self, sql: str):
        if not self.connected:
            raise Exception(f"{self.name} 未连接")
        return f"[{self.name}] 查询结果: {sql}"


class ResourceDict(TypedDict):
    db: AsyncDatabase
    cache: AsyncDatabase
    logger: AsyncDatabase

async def get_multiple_resources():
    """使用 AsyncExitStack 在依赖中管理多个资源"""
    async with AsyncExitStack() as stack:
        # 同时获取多个资源
        db = await stack.enter_async_context(AsyncDatabase("MainDB"))
        cache = await stack.enter_async_context(AsyncDatabase("Cache"))
        
        # 返回所有资源
        yield ResourceDict(
            db=db,
            cache=cache
        )
        # 函数结束时，所有资源自动清理



@app.get("/user/{user_id}")
async def get_user(
    user_id: int,
    resources: ResourceDict = Depends(get_multiple_resources)
):
    """使用多个资源的端点"""
    # 先检查缓存
    cache_result = await resources["cache"].query(f"GET user:{user_id}")
    
    # 从数据库查询
    db_result = await resources["db"].query(f"SELECT * FROM users WHERE id={user_id}")
    
    return {
        "user_id": user_id,
        "cache": cache_result,
        "database": db_result
    }



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


    # 运行命令： python -m src.learning_common_lib.python基础.上下文管理器.AsyncExitStack_fastapi注入
    # 测试命令：
    # curl http://localhost:8000/user/123