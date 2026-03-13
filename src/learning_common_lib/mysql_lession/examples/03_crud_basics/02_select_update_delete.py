"""
目标: 演示 SQLAlchemy 2.0 风格的 select/update/delete 操作
关键 API: select(), update(), delete(), scalars(), scalar_one_or_none(), .all(), .where(), .values()
Python 版本: 3.11+
运行命令: uv run python examples/03_crud_basics/02_select_update_delete.py  (从 mysql_lession/ 目录)
预期现象: 插入样本书籍，演示多种查询方式，执行更新和删除，每步打印结果
生产提醒: update/delete 的 where 条件务必仔细检查，缺少 where 会影响全表；生产环境建议开启 echo 做 SQL 审计
"""

import asyncio
from decimal import Decimal

from sqlalchemy import String, Numeric, delete, select, update
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Book(Base):
    __tablename__ = "demo_books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), comment="书名")
    author: Mapped[str] = mapped_column(String(50), comment="作者")
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2), comment="价格")

    def __repr__(self) -> str:
        return f"<Book(id={self.id}, title={self.title!r}, author={self.author!r}, price={self.price})>"


async def print_all_books(session, label: str) -> None:
    """辅助函数：打印全部书籍"""
    result = await session.execute(select(Book).order_by(Book.id))
    books = result.scalars().all()
    print(f"\n{'='*50}")
    print(f"  {label}（共 {len(books)} 条）")
    print(f"{'='*50}")
    for b in books:
        print(f"  {b}")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # 先删掉 Base 里声明的所有表（如果不存在就什么都不做）
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_books 已创建")

    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # ── 插入样本数据 ──
    async with async_session() as session:
        books = [
            Book(title="Python 编程", author="张三", price=Decimal("59.90")),
            Book(title="数据结构与算法", author="李四", price=Decimal("79.00")),
            Book(title="机器学习实战", author="王五", price=Decimal("99.50")),
            Book(title="深度学习入门", author="张三", price=Decimal("68.00")),
            Book(title="Web 开发指南", author="赵六", price=Decimal("45.00")),
        ]
        session.add_all(books)
        await session.commit()
        print("插入 5 条样本数据")

    # ══════════════════════════════════════
    # SELECT 查询
    # ══════════════════════════════════════
    async with async_session() as session:
        await print_all_books(session, "全部书籍")

        # --- scalars().all() 返回列表 ---
        print("\n--- scalars().all(): 查询张三的所有书 ---")
        stmt = select(Book).where(Book.author == "张三")
        result = await session.execute(stmt)
        zhang_books = result.scalars().all()
        for b in zhang_books:
            print(f"  {b}")

        # --- scalar_one_or_none() 返回单个或 None ---
        print("\n--- scalar_one_or_none(): 查询《机器学习实战》 ---")
        stmt = select(Book).where(Book.title == "机器学习实战")
        result = await session.execute(stmt)
        ml_book = result.scalar_one_or_none()
        print(f"  找到: {ml_book}" if ml_book else "  未找到")

        # --- 多条件过滤 ---
        print("\n--- 多条件: 价格 > 60 且作者为张三 ---")
        stmt = select(Book).where(Book.price > 60, Book.author == "张三")
        result = await session.execute(stmt)
        filtered = result.scalars().all()
        for b in filtered:
            print(f"  {b}")

        # --- 排序 + 限制 ---
        print("\n--- 按价格降序取前 3 ---")
        stmt = select(Book).order_by(Book.price.desc()).limit(3)
        result = await session.execute(stmt)
        top3 = result.scalars().all()
        for b in top3:
            print(f"  {b}")

    # ══════════════════════════════════════
    # UPDATE 更新
    # ══════════════════════════════════════
    async with async_session() as session:
        # --- 批量更新：张三的书全部涨价 10% ---
        stmt = (
            update(Book)
            .where(Book.author == "张三")
            .values(price=Book.price * Decimal("1.1"))
        )
        result = await session.execute(stmt)
        await session.commit()
        print(f"\n批量更新: 张三的书涨价 10%，影响 {result.rowcount} 行")

    async with async_session() as session:
        await print_all_books(session, "更新后的书籍")

    # ══════════════════════════════════════
    # DELETE 删除
    # ══════════════════════════════════════
    async with async_session() as session:
        # --- 删除价格低于 50 的书 ---
        stmt = delete(Book).where(Book.price < 50)
        result = await session.execute(stmt)
        await session.commit()
        print(f"\n删除价格 < 50 的书，影响 {result.rowcount} 行")

    async with async_session() as session:
        await print_all_books(session, "删除后的书籍")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
