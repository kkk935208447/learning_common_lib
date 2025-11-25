# 异步上下文管理器 AsyncExitStack 用法
# AsyncExitStack 的作用
# AsyncExitStack 是 Python 标准库 contextlib 中的异步上下文管理器，它的主要作用是：

# 动态管理多个异步上下文管理器：可以在运行时动态地进入多个异步上下文
# 确保资源正确清理：即使发生异常，也能保证所有资源按正确顺序清理
# 简化嵌套上下文管理：避免多层嵌套的 async with 语句

import asyncio
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))



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
    

from contextlib import AsyncExitStack


async def main():
    async with AsyncExitStack() as stack:
        db1 = await stack.enter_async_context(AsyncDatabase("DB1"))
        db2 = await stack.enter_async_context(AsyncDatabase("DB2"))
        
        results = await asyncio.gather(
            db1.query("SELECT * FROM users"),
            db2.query("SELECT * FROM orders")
        )
        for result in results:
            print(result)

        raise Exception("模拟异常")   # 触发异常，确保 db1 和 db2 都能正确关闭

        # 结束时，AsyncExitStack 会自动调用 db1.__aexit__() 和 db2.__aexit__()，
        # 退出 async with 块后，所有数据库连接都已自动关闭


if __name__ == "__main__":
    asyncio.run(main())