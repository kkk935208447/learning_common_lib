"""
目标: 演示 begin_nested() 保存点 (SAVEPOINT) 实现部分回滚
关键 API: session.begin_nested(), SAVEPOINT, ROLLBACK TO SAVEPOINT
Python 版本: 3.11+
运行命令: uv run python examples/07_transactions/02_nested_savepoint.py  (从 mysql_lession/ 目录)
预期现象: 创建订单成功；添加商品时某项失败只回滚该保存点，订单和其他商品保留
生产提醒: MySQL InnoDB 支持 SAVEPOINT；保存点不宜嵌套过深，每层都有开销
"""

import asyncio

from sqlalchemy import ForeignKey, Integer, String, Numeric, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "ex07_02_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"Order(id={self.id}, customer={self.customer!r}, status={self.status!r})"


class OrderItem(Base):
    __tablename__ = "ex07_02_order_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ex07_02_order.id"))
    product: Mapped[str] = mapped_column(String(50))
    price: Mapped[float] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"OrderItem(id={self.id}, product={self.product!r}, price={self.price})"


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# 模拟商品校验：价格为负数视为非法
def validate_item(product: str, price: float) -> None:
    if price < 0:
        raise ValueError(f"商品 '{product}' 价格非法: {price}")


async def show_order(session: AsyncSession, order_id: int) -> None:
    """查询并打印订单及其商品"""
    stmt = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order is None:
        print("  订单不存在")
        return
    print(f"  {order}")
    for item in order.items:
        print(f"    └─ {item}")
    if not order.items:
        print(f"    └─ (无商品)")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # ── 场景 1: 所有商品都合法，全部提交 ──
    print_section("场景 1: 所有商品合法 — 全部提交")
    async with AsyncSession(engine) as session, session.begin():
        order = Order(customer="张三", status="pending")
        session.add(order)
        await session.flush()  # 获取 order.id
        print(f"  创建订单: {order}")

        items_to_add = [
            ("键盘", 299),
            ("鼠标", 99),
            ("显示器", 1999),
        ]
        for product, price in items_to_add:
            # 每个商品用一个 savepoint
            async with session.begin_nested():
                validate_item(product, price)
                item = OrderItem(order_id=order.id, product=product, price=price)
                session.add(item)
                print(f"  ✅ 添加商品: {product} ¥{price}")

        order.status = "confirmed"
        # session.begin() 上下文结束时自动 commit

    async with AsyncSession(engine) as session:
        print("\n  最终订单状态:")
        await show_order(session, 1)

    # ── 场景 2: 某个商品非法，只回滚该 savepoint ──
    print_section("场景 2: 部分商品非法 — 只回滚 savepoint，保留其他商品")
    async with AsyncSession(engine) as session, session.begin():
        order = Order(customer="李四", status="pending")
        session.add(order)
        await session.flush()
        print(f"  创建订单: {order}")

        items_to_add = [
            ("耳机", 599),
            ("数据线", -10),   # 非法价格！
            ("充电器", 129),
        ]
        for product, price in items_to_add:
            try:
                async with session.begin_nested():
                    validate_item(product, price)
                    item = OrderItem(order_id=order.id, product=product, price=price)
                    session.add(item)
                    print(f"  ✅ 添加商品: {product} ¥{price}")
            except ValueError as e:
                # savepoint 已自动回滚，外层事务不受影响
                print(f"  ❌ 商品校验失败，savepoint 已回滚: {e}")

        order.status = "partial"
        print(f"\n  订单状态设为 'partial' (部分成功)")

    async with AsyncSession(engine) as session:
        print("\n  最终订单状态 (数据线被回滚，其他保留):")
        await show_order(session, 2)

    # ── 场景 3: 外层事务整体回滚 ──
    print_section("场景 3: 外层事务异常 — 整体回滚 (savepoint 也无效)")
    try:
        async with AsyncSession(engine) as session, session.begin():
            order = Order(customer="王五", status="pending")
            session.add(order)
            await session.flush()
            print(f"  创建订单: {order}")

            async with session.begin_nested():
                item = OrderItem(order_id=order.id, product="笔记本", price=5999)
                session.add(item)
                print(f"  ✅ 添加商品: 笔记本 ¥5999")

            # 模拟外层异常
            raise RuntimeError("支付网关超时！")
    except RuntimeError as e:
        print(f"  ❌ 外层异常: {e}")
        print(f"  整个事务 (包括 savepoint 中的数据) 全部回滚")

    async with AsyncSession(engine) as session:
        stmt = select(Order).where(Order.customer == "王五")
        result = (await session.execute(stmt)).scalar_one_or_none()
        print(f"  查询王五的订单: {result or '不存在 (已回滚)'}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ 保存点 (SAVEPOINT) 演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
