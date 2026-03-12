"""
解决什么问题: FastAPI 中数据库生命周期和 Session 注入问题，避免手动管理引擎启停和 Session 传递
输入输出约定: db_lifespan 管理引擎生命周期并注册全局异常处理器，get_db_session 作为 Depends 注入 AsyncSession
失败策略: 启动阶段引擎初始化失败直接抛出异常阻止应用启动；请求级 Session 在 with 块退出时自动关闭并归还连接；
    数据库未初始化时抛出 ConnectionError（业务异常）而非裸 RuntimeError
不适用场景: 非 FastAPI 框架；需要多数据库切换的场景（需自行扩展）
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .db_engine import (
        create_engine_factory,
        get_engine,
        dispose_engine,
        DEFAULT_DATABASE_URL,
    )
    from .db_session import async_session_factory
    from .base_model import Base
    from .error_handler import register_exception_handlers, RequestIdMiddleware
    from .error_base import ConnectionError as DbConnectionError
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.db_engine import (  # type: ignore[no-redef]
        create_engine_factory,
        get_engine,
        dispose_engine,
        DEFAULT_DATABASE_URL,
    )
    from templates.db_session import async_session_factory  # type: ignore[no-redef]
    from templates.base_model import Base  # type: ignore[no-redef]
    from templates.error_handler import register_exception_handlers, RequestIdMiddleware  # type: ignore[no-redef]
    from templates.error_base import ConnectionError as DbConnectionError  # type: ignore[no-redef]

# 模块级变量，保存 Session 工厂供依赖注入使用。
# 这里缓存的是"Session 构造器"，不是具体的 Session 实例。
# 每个请求都会创建自己的 AsyncSession，因此不会出现多个请求共享同一个 Session 的问题。
_session_factory = None


@asynccontextmanager
async def db_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI 生命周期管理器。

    启动时: 创建引擎，初始化 Session 工厂。
    关闭时: 销毁引擎，释放所有连接。

    注意: 模板统一复用 db_engine 中的全局单例 Engine，
    保证整个进程内只有一套连接池。
    """
    global _session_factory

    # 启动阶段：统一走 db_engine 单例入口，避免同一进程出现多套连接池。
    engine = get_engine()
    _session_factory = async_session_factory(engine)

    # 注册全局异常处理器和 request_id 中间件
    register_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)

    # ⚠️ 生产环境请删除以下建表代码，使用 Alembic 迁移管理表结构变更
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    print("数据库初始化完成")

    yield  # 应用运行中

    # 关闭阶段：统一释放 db_engine 的单例连接池。
    await dispose_engine()
    _session_factory = None
    print("数据库连接已释放")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入函数，获取请求级 Session。

    Session 只负责 open/close，不自动 commit。
    写操作应在 Service/Repository 层用 async with session.begin() 显式控制事务边界，
    这样读请求不会产生无意义的 commit，写请求的事务范围也更精确。

    用法:
        @app.get("/users")
        async def list_users(session: AsyncSession = Depends(get_db_session)):
            ...
    """
    if _session_factory is None:
        raise DbConnectionError(
            message="数据库未初始化，请确保 db_lifespan 已配置为 FastAPI lifespan",
        )

    async with _session_factory() as session:
        # 请求结束后 async with 会自动 close Session，并把连接归还连接池。
        # 这里不写 commit/rollback，是为了让事务边界留在业务代码里显式表达。
        yield session


async def _demo() -> None:
    """演示：创建最小 FastAPI 应用，使用 lifespan 管理数据库，通过 httpx 测试端点。"""
    global _session_factory

    import httpx
    from sqlalchemy import String, select
    from sqlalchemy.orm import Mapped, mapped_column
    try:
        from .base_model import TimestampMixin
    except ImportError:
        from templates.base_model import TimestampMixin  # type: ignore[no-redef]

    # 定义测试模型
    class Item(TimestampMixin, Base):
        """测试用模型。"""
        title: Mapped[str] = mapped_column(String(100), comment="标题")

    # 手动初始化数据库（ASGITransport 不会触发 lifespan）
    # 教程演示直接使用硬编码 URL，生产环境走环境变量
    engine = create_engine_factory(url=DEFAULT_DATABASE_URL)
    _session_factory = async_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("数据库初始化完成")

    # 创建 FastAPI 应用（lifespan 在真实部署时生效）
    app = FastAPI(lifespan=db_lifespan)

    @app.get("/items")
    async def list_items(session: AsyncSession = Depends(get_db_session)):
        """查询所有 Item。"""
        result = await session.execute(select(Item))
        items = result.scalars().all()
        return [{"id": i.id, "title": i.title} for i in items]

    @app.post("/items")
    async def create_item(title: str, session: AsyncSession = Depends(get_db_session)):
        """创建一个 Item。"""
        # 写请求显式打开事务，教学上最关键的一点是：
        # "请求级 Session" != "请求级事务"。
        # 这里的事务只覆盖真正的写操作，范围最小，也更符合企业项目习惯。
        async with session.begin():
            item = Item(title=title)
            session.add(item)
            await session.flush()
            await session.refresh(item)
        return {"id": item.id, "title": item.title}

    # 使用 httpx 的 ASGITransport 进行进程内测试
    from httpx import ASGITransport

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/items", params={"title": "测试项目"})
        print(f"POST /items 响应: {resp.status_code} {resp.json()}")

        resp = await client.get("/items")
        print(f"GET /items 响应: {resp.status_code} {resp.json()}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    _session_factory = None
    print("FastAPI 集成演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
