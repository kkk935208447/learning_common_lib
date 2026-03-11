"""
目标: 演示连接池参数配置，观察池状态，并用并发查询展示连接池工作机制
关键 API: create_async_engine(pool_size, max_overflow, pool_recycle, pool_pre_ping), engine.pool.status()
Python 版本: 3.11+
运行命令: uv run python examples/01_connection/02_connection_pool.py  (从 mysql_lession/ 目录)
预期现象: 打印连接池初始状态，并发执行多个查询后再次打印池状态，观察 checkedout/checkedin 变化
生产提醒: pool_recycle 建议设为小于 MySQL wait_timeout（默认 28800s）的值，避免拿到已断开的连接
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


async def run_query(engine, query_id: int) -> None:
    """模拟一个耗时查询，观察连接池分配"""
    async with engine.connect() as conn:
        # 打印当前查询拿到连接时的池状态
        print(f"  查询 {query_id} 获得连接 | 池状态: {engine.pool.status()}")
        result = await conn.execute(text("SELECT SLEEP(0.3)"))
        _ = result.scalar()
        print(f"  查询 {query_id} 执行完毕")


async def main() -> None:
    # ── 1. 创建带连接池参数的引擎 ──
    engine = create_async_engine(
        DATABASE_URL,
        pool_size=5,        # 池中保持的常驻连接数
        max_overflow=10,    # 超出 pool_size 后最多再创建 10 个临时连接
        pool_recycle=3600,  # 连接存活 1 小时后回收重建，防止 MySQL 超时断开
        pool_pre_ping=True, # 每次取连接前先 ping 一下，确保连接可用
        echo=False,         # 关闭 SQL 日志，让输出更清晰
    )
    print("连接池参数:")
    print(f"  pool_size     = {engine.pool.size()}")
    print(f"  max_overflow  = {engine.pool.overflow()}")
    print(f"  pool_recycle  = 3600")
    print(f"  pool_pre_ping = True")

    # ── 2. 初始池状态 ──
    print(f"\n初始池状态: {engine.pool.status()}")

    # ── 3. 并发执行 8 个查询，观察连接池分配 ──
    print("\n开始并发执行 8 个查询...")
    tasks = [run_query(engine, i) for i in range(1, 9)]
    await asyncio.gather(*tasks)

    # ── 4. 并发结束后的池状态 ──
    print(f"\n并发结束后池状态: {engine.pool.status()}")

    # ── 5. 再执行一个查询，观察连接复用 ──
    print("\n再执行一个单独查询，观察连接复用...")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 'hello_pool' AS msg"))
        print(f"  结果: {result.scalar()}")
    print(f"单独查询后池状态: {engine.pool.status()}")

    # ── 6. 释放引擎 ──
    await engine.dispose()
    print("\n引擎已释放，连接池已关闭")


if __name__ == "__main__":
    asyncio.run(main())
