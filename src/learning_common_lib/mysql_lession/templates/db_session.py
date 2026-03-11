"""
解决什么问题: Session 创建和生命周期管理问题，确保每次请求使用独立 Session 并正确关闭
输入输出约定: 输入 AsyncEngine，输出 async_sessionmaker 或通过异步生成器获取 AsyncSession
失败策略: Session 内异常由调用方处理，Session 关闭时自动归还连接
不适用场景: 需要手动控制事务边界的复杂嵌套事务场景
"""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

try:
    from .db_engine import get_engine
except ImportError:
    # 直接运行时（python templates/db_session.py）使用绝对导入
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.db_engine import get_engine  # type: ignore[no-redef]


def async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    创建异步 Session 工厂。

    expire_on_commit=False 防止提交后访问属性时触发隐式刷新（异步下会报错）。
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        # 这个配置在异步 ORM 里几乎是“默认必开”。
        # commit 后如果对象属性被标记为 expired，后续再访问属性就会尝试隐式发 SQL，
        # 在 async 场景下很容易触发 MissingGreenlet / DetachedInstanceError。
        expire_on_commit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    异步生成器：获取一个 Session，用完自动关闭。

    Session 只负责 open/close，不自动 commit/rollback。
    写操作应由调用方用 async with session.begin() 显式控制事务边界。

    用法:
        async for session in get_session():
            async with session.begin():
                await session.execute(...)
    """
    engine = get_engine()
    factory = async_session_factory(engine)

    async with factory() as session:
        # 这里不自动 commit 的原因是：
        # Session 生命周期和事务生命周期不是一回事。
        # Session 可以覆盖一个请求，而事务应只覆盖真正需要原子性的那一小段写操作。
        yield session


async def _demo() -> None:
    """演示 Session 的创建与查询。"""
    from sqlalchemy import text
    try:
        from .db_engine import create_engine_factory, DEFAULT_DATABASE_URL
    except ImportError:
        from templates.db_engine import create_engine_factory, DEFAULT_DATABASE_URL  # type: ignore[no-redef]

    # 用独立引擎演示，避免污染全局单例（教程演示直接使用硬编码 URL）
    engine = create_engine_factory(url=DEFAULT_DATABASE_URL, echo=True)
    factory = async_session_factory(engine)

    async with factory() as session:
        # 简单查询
        result = await session.execute(text("SELECT 1 AS val"))
        row = result.one()
        print(f"查询结果: {row.val}")

    await engine.dispose()
    print("Session 演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
