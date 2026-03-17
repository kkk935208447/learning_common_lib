"""
目标: 演示 N+1 问题以及 selectinload / joinedload 的解决方案
关键 API: selectinload(), joinedload(), relationship(), echo=True
Python 版本: 3.11+
运行命令: uv run python examples/09_performance/01_eager_loading.py  (从 mysql_lession/ 目录)
预期现象: 先展示 N+1 问题 (异步下直接报错)，再用 selectinload 和 joinedload 分别修复，打印 SQL 对比
生产提醒: selectinload 适合一对多 (用 IN 子查询)；joinedload 适合多对一或数据量小的关系；大集合慎用 joinedload 会产生笛卡尔积
    MissingGreenlet 的完整异常链路见 05_relationships/03_missing_greenlet_lazy_loading.py
"""

import asyncio

from sqlalchemy import ForeignKey, Integer, String, select, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
    joinedload,
)

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "ex09_01_author"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))

    books: Mapped[list["Book"]] = relationship(back_populates="author", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"Author(id={self.id}, name={self.name!r})"


class Book(Base):
    __tablename__ = "ex09_01_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int] = mapped_column(ForeignKey("ex09_01_author.id"))

    author: Mapped[Author] = relationship(back_populates="books")

    def __repr__(self) -> str:
        return f"Book(id={self.id}, title={self.title!r})"


# ── SQL 计数器 ────────────────────────────────────────────
sql_counter: int = 0


def count_sql(conn, cursor, statement, parameters, context, executemany):
    global sql_counter
    sql_counter += 1


def reset_counter() -> None:
    global sql_counter
    sql_counter = 0


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def seed_data(engine) -> None:
    """插入 5 个作者，每人 3 本书"""
    async with AsyncSession(engine) as session, session.begin():
        authors = [
            Author(name=name, books=[
                Book(title=f"{name}的作品_{i}") for i in range(1, 4)
            ])
            for name in ["鲁迅", "老舍", "巴金", "茅盾", "冰心"]
        ]
        session.add_all(authors)


async def main() -> None:
    # 使用 echo=False，通过事件钩子手动计数 SQL
    engine = create_async_engine(DATABASE_URL, echo=False)

    # 注册 SQL 计数事件
    event.listen(engine.sync_engine, "before_cursor_execute", count_sql)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await seed_data(engine)

    # ── 1. N+1 问题演示 (异步下会报 MissingGreenlet 错误) ──
    print_section("1. N+1 问题 — 异步下懒加载直接报错")
    async with AsyncSession(engine) as session:
        stmt = select(Author)
        authors = (await session.execute(stmt)).scalars().all()
        print(f"  查询到 {len(authors)} 个作者")
        for a in authors:
            try:
                # 异步模式下，访问未加载的 relationship 会抛异常
                _ = a.books
                print(f"  {a.name}: {len(a.books)} 本书")
            except Exception as e:
                print(f"  ❌ 访问 {a.name}.books 报错: {type(e).__name__}")
                original = getattr(e, 'orig', None)
                if original is not None:
                    print(f"     内层根因: {type(original).__name__}: {original}")
                print("     异步 ORM 不支持隐式懒加载，必须使用预加载策略！")
                print("     更完整的 MissingGreenlet 触发链路，请看 05_relationships/03_missing_greenlet_lazy_loading.py")
                break

    # ── 2. selectinload 修复 ──
    print_section("2. selectinload() — 用 SELECT ... WHERE id IN (...) 预加载")
    reset_counter()
    async with AsyncSession(engine) as session:
        stmt = select(Author).options(selectinload(Author.books))
        authors = (await session.execute(stmt)).scalars().all()
        for a in authors:
            book_titles = ", ".join(b.title for b in a.books)
            print(f"  {a.name}: [{book_titles}]")
    print(f"\n  SQL 执行次数: {sql_counter} (1 次查作者 + 1 次 IN 查所有书 = 2 次)")

    # ── 3. joinedload 修复 ──
    print_section("3. joinedload() — 用 LEFT JOIN 一次查出")
    reset_counter()
    async with AsyncSession(engine) as session:
        stmt = select(Author).options(joinedload(Author.books))
        authors = (await session.execute(stmt)).unique().scalars().all()
        for a in authors:
            book_titles = ", ".join(b.title for b in a.books)
            print(f"  {a.name}: [{book_titles}]")
    print(f"\n  SQL 执行次数: {sql_counter} (1 次 LEFT JOIN 查询)")
    print("  注意: joinedload 需要 .unique() 去重，因为 JOIN 会产生重复行")

    # ── 4. 对比总结 ──
    print_section("4. selectinload vs joinedload 对比")
    print("""
  ┌──────────────┬────────────────────────────┬────────────────────────────┐
  │              │  selectinload              │  joinedload                │
  ├──────────────┼────────────────────────────┼────────────────────────────┤
  │ SQL 策略     │ 额外 SELECT ... IN (...)   │ LEFT OUTER JOIN            │
  │ 查询次数     │ 2 次 (主表 + 关联表)        │ 1 次                       │
  │ 数据传输     │ 无冗余                      │ 主表字段重复 (笛卡尔积)     │
  │ 适用关系     │ 一对多 (集合大时更优)        │ 多对一、一对一              │
  │ 注意事项     │ IN 列表过大时需分批          │ 需 .unique() 去重           │
  └──────────────┴────────────────────────────┴────────────────────────────┘
""")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("✅ 预加载策略演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
