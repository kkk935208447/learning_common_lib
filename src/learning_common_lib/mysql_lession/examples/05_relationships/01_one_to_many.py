"""
目标: 演示一对多关系：ForeignKey + relationship，使用 selectinload 预加载避免异步懒加载问题
关键 API: ForeignKey, relationship(), Mapped[list[...]], back_populates, selectinload
Python 版本: 3.11+
运行命令: uv run python examples/05_relationships/01_one_to_many.py  (从 mysql_lession/ 目录)
预期现象: 创建 Author 和 Article 表，插入作者及其文章，通过 selectinload 查询并打印关联数据
生产提醒: 异步 ORM 中禁止使用默认的 lazy loading，必须用 selectinload/joinedload 等显式加载策略
"""

import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, DateTime, func, select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


class Base(AsyncAttrs, DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "demo_authors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), comment="作者名")
    bio: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="简介")

    # 一对多关系：一个作者有多篇文章
    # back_populates 建立双向引用
    # 类型注解 Mapped[list["Article"]] 告诉 SQLAlchemy 这是一对多
    # lazy="raise" — 异步环境下必须显式加载（selectinload/joinedload），
    #   防止意外触发隐式 SQL 导致 MissingGreenlet 错误
    articles: Mapped[list["Article"]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",  # 删除作者时级联删除文章
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Author(id={self.id}, name={self.name!r})>"


class Article(Base):
    __tablename__ = "demo_articles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), comment="文章标题")
    content: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="内容")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 外键：指向 demo_authors.id
    author_id: Mapped[int] = mapped_column(
        ForeignKey("demo_authors.id"), comment="作者ID"
    )

    # 多对一关系：多篇文章属于一个作者
    # lazy="raise" — 同上，异步环境必须显式加载
    author: Mapped["Author"] = relationship(back_populates="articles", lazy="raise")

    def __repr__(self) -> str:
        return f"<Article(id={self.id}, title={self.title!r})>"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    # 建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表 demo_authors, demo_articles 已创建\n")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── 插入数据：通过关系直接关联 ──
    async with session_factory() as session:
        async with session.begin():
            # 创建作者，同时通过 articles 列表直接关联文章
            author1 = Author(
                name="鲁迅",
                bio="中国现代文学奠基人",
                articles=[
                    Article(title="狂人日记", content="某君昆仲，今隐其名..."),
                    Article(title="阿Q正传", content="阿Q没有家..."),
                    Article(title="孔乙己", content="鲁镇的酒店的格局..."),
                ],
            )
            author2 = Author(
                name="老舍",
                bio="人民艺术家",
                articles=[
                    Article(title="骆驼祥子", content="祥子是一个车夫..."),
                    Article(title="茶馆", content="裕泰茶馆..."),
                ],
            )
            session.add_all([author1, author2])
        print("插入 2 位作者及其文章完成")

    # ── 查询：使用 selectinload 预加载关联数据 ──
    print("\n--- 使用 selectinload 查询作者及其文章 ---")
    async with session_factory() as session:
        # selectinload 会用一条额外的 SELECT ... WHERE id IN (...) 加载关联数据
        # 这是异步场景下最推荐的加载策略
        stmt = select(Author).options(selectinload(Author.articles)).order_by(Author.id)
        result = await session.execute(stmt)
        authors = result.scalars().all()

        for author in authors:
            print(f"\n作者: {author.name}（{author.bio}）")
            print(f"  共 {len(author.articles)} 篇文章:")
            for article in author.articles:
                print(f"    - {article.title} (id={article.id})")

    # ── 查询：从文章反查作者 ──
    print("\n--- 从文章反查作者 ---")
    async with session_factory() as session:
        # joinedload 也可以，但 selectinload 在一对多场景下通常更高效
        from sqlalchemy.orm import joinedload

        stmt = (
            select(Article)
            .options(joinedload(Article.author))
            .where(Article.title == "骆驼祥子")
        )
        result = await session.execute(stmt)
        article = result.scalar_one_or_none()
        if article:
            print(f"文章《{article.title}》的作者是: {article.author.name}")

    # ── 演示级联删除 ──
    print("\n--- 级联删除演示 ---")
    async with session_factory() as session:
        async with session.begin():
            stmt = select(Author).options(selectinload(Author.articles)).where(Author.name == "老舍")
            result = await session.execute(stmt)
            author_to_delete = result.scalar_one()
            article_count = len(author_to_delete.articles)
            await session.delete(author_to_delete)
        print(f"删除作者「老舍」，级联删除 {article_count} 篇文章")

    # 验证删除结果
    async with session_factory() as session:
        result = await session.execute(select(Author).options(selectinload(Author.articles)))
        remaining = result.scalars().all()
        print(f"剩余作者: {[a.name for a in remaining]}")
        result2 = await session.execute(select(Article))
        remaining_articles = result2.scalars().all()
        print(f"剩余文章: {[a.title for a in remaining_articles]}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("\n表已删除")

    await engine.dispose()
    print("引擎已释放")


if __name__ == "__main__":
    asyncio.run(main())
