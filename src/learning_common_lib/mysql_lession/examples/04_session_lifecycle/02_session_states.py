"""
目标: 演示 ORM 对象的五种状态（transient/pending/persistent/detached/deleted）及 expire_on_commit 行为
关键 API: inspect(obj), InstanceState.transient/pending/persistent/detached/deleted, expire_on_commit
Python 版本: 3.11+
运行命令: uv run python examples/04_session_lifecycle/02_session_states.py  (从 mysql_lession/ 目录)
预期现象: 逐步打印对象在每个生命周期阶段的状态，对比 expire_on_commit=True/False 的区别
生产提醒: 异步场景下推荐 expire_on_commit=False，否则 commit 后访问属性会触发隐式 IO 导致报错
"""

import asyncio

from sqlalchemy import String, inspect, select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "demo_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), comment="名称")

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, name={self.name!r})>"


def show_state(obj, label: str) -> None:
    """打印对象当前的 ORM 状态"""
    state = inspect(obj)
    flags = []
    if state.transient:
        flags.append("transient(瞬态)")
    if state.pending:
        flags.append("pending(待定)")
    if state.persistent:
        flags.append("persistent(持久)")
    if state.detached:
        flags.append("detached(游离)")
    if state.deleted:
        flags.append("deleted(已删除)")
    print(f"  [{label}] 状态: {', '.join(flags)}")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # 先删掉 Base 里声明的所有表（如果不存在就什么都不做）
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_items 已创建\n")

    # ══════════════════════════════════════════════
    # 第一部分：五种状态演示
    # ══════════════════════════════════════════════
    print("=" * 50)
    print("  ORM 对象五种状态演示")
    print("=" * 50)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # ── 1. Transient（瞬态）：刚创建，未关联任何 session ──
        item = Item(name="测试物品")
        show_state(item, "1. 刚创建对象")

        # ── 2. Pending（待定）：add 到 session，但未 flush/commit ──
        session.add(item)
        show_state(item, "2. session.add() 后")

        # ── 3. Persistent（持久）：flush 后，数据库中有对应行 ──
        await session.flush()
        show_state(item, "3. session.flush() 后")
        print(f"       此时已有 id: {item.id}")

        # commit 后仍然是 persistent（因为 session 还没关闭）
        await session.commit()
        show_state(item, "4. session.commit() 后")

        # ── 4. Deleted（已删除）：标记删除但未提交 ──
        item_id = item.id  # 保存 id，rollback 后属性会过期
        await session.delete(item)
        await session.flush()
        show_state(item, "5. session.delete() + flush 后")

        # 回滚删除操作，让对象恢复 persistent
        await session.rollback()
        # rollback 后需要重新查询（用之前保存的 id，避免访问过期属性触发隐式 IO）
        item = await session.get(Item, item_id)
        if item:
            show_state(item, "6. rollback 后重新查询")

    # ── 5. Detached（游离）：session 关闭后 ──
    # session 已关闭（退出 async with），对象变为 detached
    if item:
        show_state(item, "7. session 关闭后")

    # ══════════════════════════════════════════════
    # 第二部分：expire_on_commit 对比
    # ══════════════════════════════════════════════
    print(f"\n{'=' * 50}")
    print("  expire_on_commit 对比")
    print(f"{'=' * 50}")

    # --- expire_on_commit=False（推荐用于异步） ---
    print("\n--- expire_on_commit=False ---")
    factory_no_expire = async_sessionmaker(engine, expire_on_commit=False)
    async with factory_no_expire() as session:
        item_a = Item(name="不过期对象")
        session.add(item_a)
        await session.commit()
        # commit 后直接访问属性，不会触发隐式查询
        print(f"  commit 后访问 name: {item_a.name}  （直接可用，无需重新查询）")
        print(f"  commit 后访问 id:   {item_a.id}")

    # --- expire_on_commit=True（默认值） ---
    print("\n--- expire_on_commit=True（默认） ---")
    factory_expire = async_sessionmaker(engine, expire_on_commit=True)
    async with factory_expire() as session:
        item_b = Item(name="会过期对象")
        session.add(item_b)
        await session.commit()
        # commit 后属性被标记为过期，异步中直接访问会报错
        state = inspect(item_b)
        print(f"  commit 后属性是否过期: {state.expired}")
        print("  异步场景下此时访问 item_b.name 会报 MissingGreenlet 错误")
        print("  需要先 await session.refresh(item_b) 才能安全访问")
        await session.refresh(item_b)
        print(f"  refresh 后访问 name: {item_b.name}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
