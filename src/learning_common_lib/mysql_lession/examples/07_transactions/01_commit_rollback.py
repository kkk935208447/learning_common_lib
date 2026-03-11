"""
目标: 演示事务的 commit / rollback 以及异常时的自动回滚机制
关键 API: session.begin(), session.commit(), session.rollback(), async with session.begin()
Python 版本: 3.11+
运行命令: uv run python examples/07_transactions/01_commit_rollback.py  (从 mysql_lession/ 目录)
预期现象: 成功转账后余额变化；余额不足时回滚，余额不变；异常时自动回滚
生产提醒: 生产环境推荐使用 async with session.begin() 上下文管理器，自动处理 commit/rollback，避免手动遗漏
"""

import asyncio

from sqlalchemy import Integer, String, Numeric, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "ex07_01_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    balance: Mapped[float] = mapped_column(Numeric(12, 2))

    def __repr__(self) -> str:
        return f"Account(id={self.id}, name={self.name!r}, balance={self.balance})"


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def show_balances(session: AsyncSession) -> None:
    """打印所有账户余额"""
    result = await session.execute(select(Account).order_by(Account.id))
    for acc in result.scalars().all():
        print(f"  {acc.name}: {acc.balance}")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # 初始化账户
    async with AsyncSession(engine) as session, session.begin():
        session.add_all([
            Account(name="Alice", balance=10000),
            Account(name="Bob", balance=5000),
        ])

    # ── 1. 成功转账: 手动 commit ──
    print_section("1. 成功转账 — 手动 commit")
    async with AsyncSession(engine) as session:
        await session.begin()
        alice = (await session.execute(
            select(Account).where(Account.name == "Alice")
        )).scalar_one()
        bob = (await session.execute(
            select(Account).where(Account.name == "Bob")
        )).scalar_one()

        amount = 3000
        print(f"  转账前:")
        print(f"    Alice: {alice.balance}, Bob: {bob.balance}")
        print(f"  转账金额: {amount}")

        alice.balance = float(alice.balance) - amount
        bob.balance = float(bob.balance) + amount
        await session.commit()
        print(f"  转账后 (已 commit):")

    async with AsyncSession(engine) as session:
        await show_balances(session)

    # ── 2. 余额不足 → 手动 rollback ──
    print_section("2. 余额不足 — 手动 rollback")
    async with AsyncSession(engine) as session:
        await session.begin()
        alice = (await session.execute(
            select(Account).where(Account.name == "Alice")
        )).scalar_one()
        bob = (await session.execute(
            select(Account).where(Account.name == "Bob")
        )).scalar_one()

        amount = 99999
        print(f"  尝试转账: Alice → Bob {amount}")
        if float(alice.balance) < amount:
            print(f"  ❌ 余额不足 (Alice 余额={alice.balance})，执行 rollback")
            await session.rollback()
        else:
            alice.balance = float(alice.balance) - amount
            bob.balance = float(bob.balance) + amount
            await session.commit()

    print("  rollback 后余额不变:")
    async with AsyncSession(engine) as session:
        await show_balances(session)

    # ── 3. 异常自动回滚: async with session.begin() ──
    print_section("3. 异常自动回滚 — async with session.begin()")
    print("  使用 async with session.begin() 时，异常会自动触发 rollback")
    try:
        async with AsyncSession(engine) as session, session.begin():
            alice = (await session.execute(
                select(Account).where(Account.name == "Alice")
            )).scalar_one()
            bob = (await session.execute(
                select(Account).where(Account.name == "Bob")
            )).scalar_one()

            alice.balance = float(alice.balance) - 1000
            bob.balance = float(bob.balance) + 1000
            print(f"  修改了余额 (尚未 commit)...")

            # 模拟业务异常
            raise ValueError("模拟业务逻辑异常！")
    except ValueError as e:
        print(f"  捕获异常: {e}")
        print(f"  session.begin() 上下文已自动 rollback")

    print("  自动回滚后余额不变:")
    async with AsyncSession(engine) as session:
        await show_balances(session)

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ 事务 commit/rollback 演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
