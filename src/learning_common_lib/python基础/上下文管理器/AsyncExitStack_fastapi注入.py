# ==================== 示例 2: FastAPI 依赖注入中使用 ====================
# 异步上下文管理器 AsyncExitStack 用法
# AsyncExitStack 的作用
# AsyncExitStack 是 Python 标准库 contextlib 中的异步上下文管理器，它的主要作用是：

# 动态管理多个异步上下文管理器：可以在运行时动态地进入多个异步上下文
# 确保资源正确清理：即使发生异常，也能保证所有资源按正确顺序清理
# 简化嵌套上下文管理：避免多层嵌套的 async with 语句


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
        await asyncio.sleep(8)  # 模拟查询延迟
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
        
        
        yield ResourceDict(   # ⚠️ 这个 yield 是特殊的, FastAPI 会在这里"暂停"函数执行, 等待路由函数处理完请求后再继续
            db=db,
            cache=cache
        )
        # 函数结束时，所有资源自动清理
        # 执行过程：
            # 1. 依赖函数开始
            # 2. 进入 AsyncExitStack
            # 数据库 进入上下文（__aenter__）
            # 缓存 进入上下文（__aenter__）
            # 3. 所有资源已创建，准备 yield
            # 路由函数执行中
            # 数据库状态: True  ✅
            # 缓存状态: True    ✅
            # 4. 路由函数已执行完，准备清理
            # 缓存 退出上下文（__aexit__）
            # 数据库 退出上下文（__aexit__）
            # 5. AsyncExitStack 已退出，所有资源已清理



@app.get("/user/{user_id}")
async def get_user(
    user_id: int,
    resources: ResourceDict = Depends(get_multiple_resources)
):
    """使用多个资源的端点"""
    print(f"当前的user：{user_id}")
    results = await asyncio.gather(
        # 检查缓存
        resources["cache"].query(f"GET user:{user_id}"),
        # 从数据库查询
        resources["db"].query(f"SELECT * FROM users WHERE id={user_id}")
    )
    cache_result, db_result = results
    
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