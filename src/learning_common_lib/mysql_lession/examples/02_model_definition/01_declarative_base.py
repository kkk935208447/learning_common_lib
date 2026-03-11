"""
目标: 演示 DeclarativeBase + Mapped + mapped_column 定义 ORM 模型，完成建表、插入、查询
关键 API: DeclarativeBase, Mapped, mapped_column, async_sessionmaker, create_all, drop_all
Python 版本: 3.11+
运行命令: uv run python examples/02_model_definition/01_declarative_base.py  (从 mysql_lession/ 目录)
预期现象: 创建 users 表，插入一条用户记录，查询并打印，最后删除表
生产提醒: 生产环境使用 Alembic 做数据库迁移，不要在代码里直接 create_all/drop_all
"""

import asyncio
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


# ── 1. 定义 Base 类 ──
# DeclarativeBase 是 SQLAlchemy 2.0 推荐的声明式基类
# AsyncAttrs 让属性访问在异步上下文中更安全（可选但推荐）
class Base(AsyncAttrs, DeclarativeBase):
    pass


# ── 2. 定义 User 模型 ──
class User(Base):
    __tablename__ = "demo_users"

    # Mapped[int] 声明 Python 类型，mapped_column() 声明数据库列属性
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), comment="用户名")
    email: Mapped[str] = mapped_column(String(100), unique=True, comment="邮箱")
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, name={self.name!r}, email={self.email!r})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=True)

    # ── 3. 创建表 ──
    # run_sync 让我们在异步环境中调用同步的 metadata 方法
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)   # 先清理，确保幂等
        await conn.run_sync(Base.metadata.create_all)
    print("表已创建")

    # ── 4. 创建 session 工厂 ──
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # ── 5. 插入数据 ──
    async with async_session() as session:
        user = User(name="张三", email="zhangsan@example.com")
        session.add(user)
        await session.commit()
        # server_default 的字段（如 created_at）由数据库生成，commit 后需要 refresh 才能拿到
        await session.refresh(user)
        print(f"插入成功: {user}")
        print(f"  自动生成的 id: {user.id}")
        print(f"  服务端默认的 created_at: {user.created_at}")

    # ── 6. 查询数据 ──
    async with async_session() as session:
        from sqlalchemy import select

        stmt = select(User).where(User.name == "张三")
        result = await session.execute(stmt)
        found_user = result.scalar_one_or_none()
        if found_user:
            print(f"查询到用户: {found_user}")
            print(f"  邮箱: {found_user.email}")
            print(f"  创建时间: {found_user.created_at}")
        else:
            print("未找到用户")

    # ── 7. 清理：删除表 ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
