"""
解决什么问题: 引擎创建和连接池配置问题，避免每次手动拼装引擎参数
输入输出约定: 输入数据库 URL（可选，默认读环境变量），输出 AsyncEngine 实例
失败策略: URL 未配置时抛出 ValueError；连接失败由 SQLAlchemy 抛出原始异常
不适用场景: 同步 ORM 场景；需要多数据源路由的场景（需自行扩展）
"""

import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

# 教程示例用的默认连接地址（仅供 _demo() 独立运行，生产环境必须通过环境变量或参数传入）
DEFAULT_DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

# 模块级单例引擎。
# 企业项目里通常一个进程只保留一个 Engine：
# 1. 避免重复创建连接池，浪费 MySQL 连接数；
# 2. 让整个进程内的 Session 都复用同一组池化连接；
# 3. 应用关闭时只需要统一 dispose 一次。
_engine: AsyncEngine | None = None


def create_engine_factory(url: str | None = None, **kwargs) -> AsyncEngine:
    """
    创建异步引擎工厂函数。

    如果未传入 url，则从环境变量 DATABASE_URL 获取。
    两者都未设置时抛出 ValueError（fail-fast，避免生产环境误连开发库）。
    内置生产级连接池配置，可通过 kwargs 覆盖。
    """
    # URL 的决策顺序是：
    # 显式传参 > 环境变量。
    # 这里故意不再兜底回退到默认库，目的是 fail-fast：
    # 配置缺失时立刻报错，避免服务悄悄连到本地开发库。
    database_url = url or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "数据库 URL 未配置。请通过参数传入 url 或设置环境变量 DATABASE_URL。"
        )

    # 生产级连接池默认配置。
    # 这些参数的核心目标不是“越大越好”，而是：
    # 1. 保证连接可复用；
    # 2. 避免拿到 MySQL 已断开的连接；
    # 3. 在突发流量时允许有限溢出，而不是无限扩张。
    default_kwargs = {
        "pool_size": 5,          # 连接池常驻连接数
        "max_overflow": 10,      # 超出 pool_size 后允许的最大溢出连接数
        "pool_recycle": 3600,    # 连接回收时间（秒），防止 MySQL 8小时断连
        "pool_pre_ping": True,   # 每次取连接前发送 ping，检测连接是否存活
        "pool_timeout": 30,      # 连接池耗尽时等待可用连接的最长时间
        "echo": False,           # 生产环境关闭 SQL 日志
    }
    # 允许调用方覆盖默认配置
    default_kwargs.update(kwargs)

    return create_async_engine(database_url, **default_kwargs)


def get_engine() -> AsyncEngine:
    """
    获取全局单例引擎。

    首次调用时创建引擎，后续调用返回同一实例。
    """
    global _engine
    if _engine is None:
        # 首次访问时才真正创建 Engine。
        # 这种懒加载写法适合 Web 服务：只有在第一次需要 DB 时才初始化连接池。
        _engine = create_engine_factory()
    return _engine


async def dispose_engine() -> None:
    """
    销毁全局引擎，释放连接池中的所有连接。

    适用于应用关闭时的清理操作。
    """
    global _engine
    if _engine is not None:
        # dispose() 会关闭池中连接并让底层池失效。
        # 如果只 close Session 而不 dispose Engine，应用退出时 MySQL 端可能还残留 Sleep 连接。
        await _engine.dispose()
        _engine = None


async def _demo() -> None:
    """演示引擎创建、连接测试、连接池状态查看、引擎销毁。"""
    from sqlalchemy import text

    # 创建引擎（教程演示直接使用硬编码 URL，生产环境走环境变量）
    engine = create_engine_factory(url=DEFAULT_DATABASE_URL, echo=True)
    print(f"引擎创建成功: {engine.url}")

    # 执行 SELECT 1 验证连接
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        print(f"连接测试结果: {result.scalar()}")

    # 打印连接池状态
    pool = engine.pool
    print(f"连接池状态 - 大小: {pool.size()}, 已检出: {pool.checkedout()}, 溢出: {pool.overflow()}")

    # 销毁引擎
    await engine.dispose()
    print("引擎已销毁")


if __name__ == "__main__":
    asyncio.run(_demo())
