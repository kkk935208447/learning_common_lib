"""
目标: 专门演示异步 lazy loading 触发 MissingGreenlet 的完整链路，以及 3 种修复思路
关键 API: AsyncAttrs, relationship(), awaitable_attrs, selectinload, joinedload, lazy="raise"
Python 版本: 3.11+
运行命令: uv run python examples/05_relationships/03_missing_greenlet_lazy_loading.py  (从 mysql_lession/ 目录)
预期现象:
    1. 默认 lazy relationship 在异步中访问时，外层可能看到 StatementError，内层根因是 MissingGreenlet；
    2. awaitable_attrs 可以显式异步加载关系；
    3. selectinload / joinedload 是企业代码更推荐的修复方式；
    4. lazy="raise" 会更早、更明确地阻止隐式 lazy loading
生产提醒: 教程里演示 awaitable_attrs 是为了帮助理解机制；企业代码默认仍推荐
    relationship(lazy="raise") + 查询时显式 selectinload/joinedload，避免运行时隐式 IO
"""

import asyncio

from sqlalchemy import ForeignKey, Integer, String, select
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, joinedload, mapped_column, relationship, selectinload

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class LazyAuthor(Base):
    __tablename__ = "ex05_03_lazy_author"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    books: Mapped[list["LazyBook"]] = relationship(back_populates="author")


class LazyBook(Base):
    __tablename__ = "ex05_03_lazy_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int] = mapped_column(ForeignKey("ex05_03_lazy_author.id"))
    author: Mapped[LazyAuthor] = relationship(back_populates="books")


class StrictAuthor(Base):
    __tablename__ = "ex05_03_strict_author"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50))
    books: Mapped[list["StrictBook"]] = relationship(back_populates="author", lazy="raise")


class StrictBook(Base):
    __tablename__ = "ex05_03_strict_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[int] = mapped_column(ForeignKey("ex05_03_strict_author.id"))
    author: Mapped[StrictAuthor] = relationship(back_populates="books", lazy="raise")


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def book_titles(books) -> str:
    return ", ".join(book.title for book in books)


def print_exception_chain(exc: Exception) -> None:
    print(f"  外层异常类型: {type(exc).__name__}")
    print(f"  外层异常信息: {exc}")
    original = getattr(exc, "orig", None)
    if original is not None:
        print(f"  内层 orig 类型: {type(original).__name__}")
        print(f"  内层 orig 信息: {original}")
        if isinstance(original, MissingGreenlet):
            print("  结论: 真正根因是 MissingGreenlet，只是被外层 StatementError 包了一层。")


async def seed_data(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        async with session.begin():
            session.add_all(
                [
                    LazyAuthor(
                        name="鲁迅",
                        books=[
                            LazyBook(title="狂人日记"),
                            LazyBook(title="阿Q正传"),
                        ],
                    ),
                    LazyAuthor(
                        name="老舍",
                        books=[
                            LazyBook(title="骆驼祥子"),
                            LazyBook(title="茶馆"),
                        ],
                    ),
                    StrictAuthor(
                        name="巴金",
                        books=[
                            StrictBook(title="家"),
                            StrictBook(title="春"),
                        ],
                    ),
                ]
            )


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    await seed_data(factory)

    print_section("1. 默认 lazy relationship：异步里触发 MissingGreenlet")
    async with factory() as session:
        stmt = select(LazyAuthor).order_by(LazyAuthor.id)
        authors = (await session.execute(stmt)).scalars().all()
        author = authors[0]
        print(f"  已查询作者: {author.name}")
        print("  此时 books 尚未加载；访问 author.books 会尝试隐式发 SQL。")
        try:
            _ = author.books
        except Exception as exc:
            print_exception_chain(exc)

    print_section("2. AsyncAttrs.awaitable_attrs：显式异步加载关系")
    async with factory() as session:
        author = (await session.execute(select(LazyAuthor).where(LazyAuthor.name == "鲁迅"))).scalar_one()
        books = await author.awaitable_attrs.books
        print(f"  await author.awaitable_attrs.books 成功: [{book_titles(books)}]")
        print("  这说明 AsyncAttrs 能让关系加载变成显式 await。")
        print("  但团队代码更推荐在查询阶段直接预加载，而不是把关系访问散落到业务代码里。")

    print_section("3. 显式预加载：selectinload / joinedload")
    async with factory() as session:
        stmt = select(LazyAuthor).options(selectinload(LazyAuthor.books)).order_by(LazyAuthor.id)
        authors = (await session.execute(stmt)).scalars().all()
        for author in authors:
            print(f"  selectinload 后 {author.name}: [{book_titles(author.books)}]")

    async with factory() as session:
        stmt = (
            select(LazyBook)
            .options(joinedload(LazyBook.author))
            .where(LazyBook.title == "茶馆")
        )
        book = (await session.execute(stmt)).scalar_one()
        print(f"  joinedload 后《{book.title}》的作者: {book.author.name}")

    print_section("4. lazy=\"raise\"：更早阻止隐式 lazy loading")
    async with factory() as session:
        strict_author = (
            await session.execute(select(StrictAuthor).where(StrictAuthor.name == "巴金"))
        ).scalar_one()
        print(f"  已查询作者: {strict_author.name}")
        try:
            _ = strict_author.books
        except Exception as exc:
            print(f"  访问 strict_author.books 立即失败: {type(exc).__name__}")
            print(f"  错误信息: {exc}")
            print("  这比在运行时走到 StatementError/MissingGreenlet 更早暴露问题。")

    async with factory() as session:
        stmt = (
            select(StrictAuthor)
            .options(selectinload(StrictAuthor.books))
            .where(StrictAuthor.name == "巴金")
        )
        strict_author = (await session.execute(stmt)).scalar_one()
        print(f"  配合 selectinload 后恢复正常: [{book_titles(strict_author.books)}]")

    print_section("5. 结论")
    print("  推荐优先级: 查询时显式 selectinload/joinedload > awaitable_attrs > 默认 lazy loading。")
    print("  企业项目建议把 relationship 默认写成 lazy=\"raise\"，强制团队把加载策略写在查询上。")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n✅ MissingGreenlet 专项示例完成，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
