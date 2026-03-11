"""
目标: 演示泛型 Repository 基类，封装常见 CRUD 操作
关键 API: TypeVar, Generic, select(), session.get(), session.delete()
Python 版本: 3.11+
运行命令: uv run python examples/08_repository_pattern/01_generic_repository.py  (从 mysql_lession/ 目录)
预期现象: 通过 UserRepository 完成创建、查询、更新、删除，每步打印结果
生产提醒: Repository 不应持有 session，而是通过参数注入；分页/过滤等复杂查询可在子类中扩展
"""

import asyncio
from typing import Generic, TypeVar, Sequence

from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(DeclarativeBase):
    pass


# ── 泛型 Repository ──────────────────────────────────────
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """泛型仓储基类，提供通用 CRUD 方法"""

    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        self._session = session
        self._model_cls = model_cls

    async def get_by_id(self, id_: int) -> T | None:
        """按主键查询"""
        return await self._session.get(self._model_cls, id_)

    async def list_all(self) -> Sequence[T]:
        """查询全部记录"""
        stmt = select(self._model_cls)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(self, **kwargs) -> T:
        """创建并返回新实例 (需外部 commit)"""
        instance = self._model_cls(**kwargs)
        self._session.add(instance)
        # Repository 只 flush 不 commit — 事务边界由调用方（session.begin() 或 Depends）控制
        await self._session.flush()
        return instance

    async def update(self, id_: int, **kwargs) -> T | None:
        """按主键更新字段"""
        instance = await self.get_by_id(id_)
        if instance is None:
            return None
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, id_: int) -> bool:
        """按主键删除，返回是否成功"""
        instance = await self.get_by_id(id_)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True


# ── 模型 & 具体 Repository ────────────────────────────────
class User(Base):
    __tablename__ = "ex08_01_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r}, email={self.email!r})"


class UserRepository(BaseRepository[User]):
    """用户仓储 — 继承泛型基类，可扩展特有查询"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def find_by_name(self, name: str) -> Sequence[User]:
        stmt = select(User).where(User.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().all()


# ── 主逻辑 ────────────────────────────────────────────────
def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # ── 1. 创建 ──
    print_section("1. create() — 创建用户")
    async with AsyncSession(engine) as session, session.begin():
        repo = UserRepository(session)
        u1 = await repo.create(name="张三", email="zhangsan@example.com")
        u2 = await repo.create(name="李四", email="lisi@example.com")
        u3 = await repo.create(name="王五", email="wangwu@example.com")
        print(f"  创建: {u1}")
        print(f"  创建: {u2}")
        print(f"  创建: {u3}")

    # ── 2. 查询全部 ──
    print_section("2. list_all() — 查询全部")
    async with AsyncSession(engine) as session:
        repo = UserRepository(session)
        users = await repo.list_all()
        for u in users:
            print(f"  {u}")

    # ── 3. 按 ID 查询 ──
    print_section("3. get_by_id() — 按主键查询")
    async with AsyncSession(engine) as session:
        repo = UserRepository(session)
        user = await repo.get_by_id(1)
        print(f"  ID=1: {user}")
        user = await repo.get_by_id(999)
        print(f"  ID=999: {user} (不存在)")

    # ── 4. 子类扩展方法 ──
    print_section("4. find_by_name() — 子类扩展查询")
    async with AsyncSession(engine) as session:
        repo = UserRepository(session)
        users = await repo.find_by_name("张三")
        for u in users:
            print(f"  {u}")

    # ── 5. 更新 ──
    print_section("5. update() — 更新用户")
    async with AsyncSession(engine) as session, session.begin():
        repo = UserRepository(session)
        updated = await repo.update(1, name="张三(已改名)", email="new_zhangsan@example.com")
        print(f"  更新后: {updated}")

    async with AsyncSession(engine) as session:
        repo = UserRepository(session)
        print(f"  重新查询确认: {await repo.get_by_id(1)}")

    # ── 6. 删除 ──
    print_section("6. delete() — 删除用户")
    async with AsyncSession(engine) as session, session.begin():
        repo = UserRepository(session)
        ok = await repo.delete(2)
        print(f"  删除 ID=2: {'成功' if ok else '失败'}")
        ok = await repo.delete(999)
        print(f"  删除 ID=999: {'成功' if ok else '失败 (不存在)'}")

    async with AsyncSession(engine) as session:
        repo = UserRepository(session)
        print("  剩余用户:")
        for u in await repo.list_all():
            print(f"    {u}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ 泛型 Repository 演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
