"""
目标: 演示 create_async_engine 创建异步引擎，并通过 text() 执行原生 SQL
关键 API: create_async_engine, AsyncEngine, text(), engine.connect(), engine.begin()
Python 版本: 3.11+
运行命令: uv run python examples/01_connection/01_async_engine_basic.py  (从 mysql_lession/ 目录)
预期现象: 打印 SELECT 1 的结果、通过 begin() 自动提交建表并查询、最后清理并释放引擎
生产提醒: 生产环境务必使用环境变量管理数据库连接串，不要硬编码密码
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


async def main() -> None:
    # ── 1. 创建异步引擎 ──
    engine = create_async_engine(DATABASE_URL, echo=True) # echo=True：将执行的 SQL 语句（以及绑定参数等调试信息）输出到标准输出（一般是终端），方便你在开发/调试时观察实际发出的 SQL。
    print("✅ 异步引擎创建成功")

    # ── 2. 使用 connect() 执行只读查询 ──
    # connect() 不会自动提交，需要手动 commit（或仅做读操作）
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 AS ping"))  # SELECT 1 AS ping 常用于数据库连通性/心跳检测
        row = result.one()
        print(f"📡 SELECT 1 返回: {row[0]}")

    # ── 3. 使用 begin() 执行写操作（自动提交） ──
    # “开启事务 + 自动提交/回滚”的语法糖，begin() 会在退出上下文时自动 commit，出异常则 rollback
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _engine_demo (
                id INT AUTO_INCREMENT PRIMARY KEY,
                msg VARCHAR(100)
            )
        """))
        await conn.execute(
            text("INSERT INTO _engine_demo (msg) VALUES (:msg)"),
            {"msg": "你好，异步引擎"},
        )
        print("📝 通过 begin() 自动提交：建表 + 插入完成")

    # ── 4. 再次读取验证 ──
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT * FROM _engine_demo"))
        rows = result.all()
        for r in rows:
            print(f"  行: id={r[0]}, msg={r[1]}")

    # ── 5. 清理：删除演示表 ──
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _engine_demo"))
        print("🧹 演示表已删除")

    # ── 6. 释放引擎持有的连接池资源 ──
    await engine.dispose()
    print("🔌 引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
