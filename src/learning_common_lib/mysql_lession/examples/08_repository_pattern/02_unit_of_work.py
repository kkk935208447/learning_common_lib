"""
目标: 演示 Unit of Work 模式 — 统一管理 session 和多个 Repository
关键 API: AsyncSession, async context manager, Repository 注入
Python 版本: 3.11+
运行命令: uv run python examples/08_repository_pattern/02_unit_of_work.py  (从 mysql_lession/ 目录)
预期现象: 通过 UnitOfWork 上下文同时操作 User 和 Order，成功时一起提交，失败时一起回滚
生产提醒: UoW 的 session_factory 应由外部注入 (如 FastAPI 的 Depends)；避免在 UoW 外部持有 ORM 对象引用
"""

import asyncio
from typing import Generic, TypeVar, Sequence

from sqlalchemy import ForeignKey, Integer, String, Numeric, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(DeclarativeBase):
    pass


# ── 模型 ──────────────────────────────────────────────────
class User(Base):
    __tablename__ = "ex08_02_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))

    def __repr__(self) -> str:
        return f"User(id={self.id}, name={self.name!r})"


class Order(Base):
    __tablename__ = "ex08_02_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("ex08_02_user.id"))
    product: Mapped[str] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Numeric(10, 2))

    def __repr__(self) -> str:
        return f"Order(id={self.id}, user_id={self.user_id}, product={self.product!r}, amount={self.amount})"


# ── 泛型 Repository ──────────────────────────────────────
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        self._session = session
        self._model_cls = model_cls

    async def get_by_id(self, id_: int) -> T | None:
        return await self._session.get(self._model_cls, id_)

    async def list_all(self) -> Sequence[T]:
        result = await self._session.execute(select(self._model_cls))
        return result.scalars().all()

    async def create(self, **kwargs) -> T:
        instance = self._model_cls(**kwargs)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def delete(self, id_: int) -> bool:
        instance = await self.get_by_id(id_)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)


class OrderRepository(BaseRepository[Order]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order)

    async def list_by_user(self, user_id: int) -> Sequence[Order]:
        stmt = select(Order).where(Order.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()


# ── Unit of Work ──────────────────────────────────────────
class UnitOfWork:
    """
    工作单元: 管理一个 session 的生命周期，并暴露各 Repository。
    用法:
        async with UnitOfWork(session_factory) as uow:
            user = await uow.users.create(name="张三")
            await uow.orders.create(user_id=user.id, ...)
            await uow.commit()
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._session_factory()
        self.users = UserRepository(self._session)
        self.orders = OrderRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            await self.rollback()
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


# ── 主逻辑 ────────────────────────────────────────────────
def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # ── 1. 成功场景: 创建用户 + 订单，一起提交 ──
    print_section("1. 成功场景 — 创建用户和订单，统一 commit")
    async with UnitOfWork(session_factory) as uow:
        user = await uow.users.create(name="张三")
        print(f"  创建用户: {user}")

        o1 = await uow.orders.create(user_id=user.id, product="机械键盘", amount=599)
        o2 = await uow.orders.create(user_id=user.id, product="无线鼠标", amount=199)
        print(f"  创建订单: {o1}")
        print(f"  创建订单: {o2}")

        await uow.commit()
        print("  ✅ 统一提交成功")

    # 验证数据
    async with UnitOfWork(session_factory) as uow:
        users = await uow.users.list_all()
        orders = await uow.orders.list_all()
        print(f"\n  数据库中: {len(users)} 个用户, {len(orders)} 个订单")
        for u in users:
            print(f"    {u}")
            for o in await uow.orders.list_by_user(u.id):
                print(f"      └─ {o}")

    # ── 2. 失败场景: 异常导致自动回滚 ──
    print_section("2. 失败场景 — 异常触发自动 rollback")
    try:
        async with UnitOfWork(session_factory) as uow:
            user2 = await uow.users.create(name="李四")
            print(f"  创建用户: {user2}")

            await uow.orders.create(user_id=user2.id, product="显示器", amount=2999)
            print(f"  创建订单: 显示器 ¥2999")

            # 模拟业务异常
            raise ValueError("库存不足，无法下单！")
    except ValueError as e:
        print(f"  ❌ 捕获异常: {e}")
        print(f"  UnitOfWork.__aexit__ 已自动 rollback")

    # 验证: 李四和订单不应存在
    async with UnitOfWork(session_factory) as uow:
        users = await uow.users.list_all()
        print(f"\n  回滚后数据库中仍然只有: {len(users)} 个用户")
        for u in users:
            print(f"    {u}")

    # ── 3. 手动 rollback 场景 ──
    print_section("3. 手动 rollback 场景")
    async with UnitOfWork(session_factory) as uow:
        user3 = await uow.users.create(name="王五")
        print(f"  创建用户: {user3}")

        # 业务检查不通过，手动回滚
        print("  业务校验不通过，手动 rollback")
        await uow.rollback()

    async with UnitOfWork(session_factory) as uow:
        users = await uow.users.list_all()
        print(f"  手动回滚后数据库中仍然只有: {len(users)} 个用户")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ Unit of Work 模式演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
