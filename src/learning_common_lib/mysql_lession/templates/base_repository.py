"""
解决什么问题: CRUD 操作重复编写问题，每个模型都要写一遍增删改查非常冗余
输入输出约定: 泛型仓储接收 AsyncSession 和模型类型，提供标准 CRUD 方法
失败策略: 查询不到返回 None/空列表；删除不存在的记录返回 False；异常由调用方处理
不适用场景: 复杂联表查询、聚合统计等场景（需自行编写查询逻辑）
"""

import asyncio
from typing import TypeVar, Generic

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .base_model import Base
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.base_model import Base  # type: ignore[no-redef]

# 泛型类型变量，约束为 Base 的子类
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    泛型 CRUD 仓储基类。

    用法:
        repo = BaseRepository(session, User)
        user = await repo.create(User(name="张三"))
        user = await repo.get_by_id(1)
    """

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: int) -> T | None:
        """根据主键 ID 查询单条记录。"""
        return await self.session.get(self.model, id)

    async def list_all(self, offset: int = 0, limit: int = 100) -> list[T]:
        """分页查询所有记录。"""
        # Repository 负责“如何查”，但不负责“何时提交事务”。
        # 这样同一个 Session 下可以组合多个 Repository，一起放到同一个事务里提交。
        stmt = select(self.model).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, obj: T, *, refresh: bool = True) -> T:
        """
        新增一条记录并返回。

        refresh=True（默认）会多一次 SELECT 往返以加载 server_default 字段（id、created_at 等）。
        高 QPS 场景下如果不需要立即读取这些字段，传 refresh=False 可省掉这次往返。
        """
        self.session.add(obj)
        # flush 的作用是“把当前变更尽快发给数据库”，但事务还没有提交。
        # 典型用途：
        # 1. 立刻拿到自增主键；
        # 2. 在同一事务里继续创建依赖这个主键的其他对象；
        # 3. 提前暴露约束错误，而不是等到最终 commit 才一起爆出。
        await self.session.flush()
        if refresh:
            # refresh 会再发一条 SELECT，把数据库端生成的默认值回填到 ORM 对象。
            # 例如 created_at、updated_at、trigger 生成字段等。
            await self.session.refresh(obj)
        return obj

    async def update(self, id: int, *, refresh: bool = True, **kwargs) -> T | None:
        """
        根据 ID 更新记录，返回更新后的对象；不存在则返回 None。

        refresh 参数含义同 create。
        """
        obj = await self.get_by_id(id)
        if obj is None:
            return None
        for key, value in kwargs.items():
            # setattr 只是修改 ORM 内存态；
            # 真正 UPDATE SQL 的发出时机是在 flush / commit。
            setattr(obj, key, value)
        await self.session.flush()
        if refresh:
            await self.session.refresh(obj)
        return obj

    async def delete(self, id: int) -> bool:
        """根据 ID 删除记录，成功返回 True，不存在返回 False。"""
        obj = await self.get_by_id(id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True

    async def count(self) -> int:
        """统计当前模型的总记录数。"""
        stmt = select(sa_func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return result.scalar_one()


async def _demo() -> None:
    """演示：定义 User 模型，使用 BaseRepository 完成完整 CRUD 流程。"""
    from sqlalchemy import String
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    try:
        from .base_model import TimestampMixin
    except ImportError:
        from templates.base_model import TimestampMixin  # type: ignore[no-redef]

    # 定义 User 模型
    class User(TimestampMixin, Base):
        """用户模型。"""
        name: Mapped[str] = mapped_column(String(50), comment="用户名")
        email: Mapped[str] = mapped_column(String(100), comment="邮箱")

    # 创建引擎和表
    engine = create_async_engine(
        "mysql+asyncmy://root:123456@localhost:3306/tutorial_db",
        echo=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        repo = BaseRepository(session, User)

        # 创建
        user = await repo.create(User(name="张三", email="zhangsan@example.com"))
        print(f"创建用户 - id: {user.id}, name: {user.name}")

        # 查询
        found = await repo.get_by_id(user.id)
        print(f"查询用户 - id: {found.id}, name: {found.name}")

        # 列表
        users = await repo.list_all()
        print(f"用户总数: {len(users)}")

        # 计数
        total = await repo.count()
        print(f"count() 结果: {total}")

        # 更新
        updated = await repo.update(user.id, name="李四", email="lisi@example.com")
        print(f"更新用户 - id: {updated.id}, name: {updated.name}")

        # 删除
        deleted = await repo.delete(user.id)
        print(f"删除结果: {deleted}")

        await session.commit()

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("CRUD 演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
