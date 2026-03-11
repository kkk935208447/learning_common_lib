"""
目标: 演示 offset/limit 分页、cursor 分页以及 order_by 排序
关键 API: order_by(), asc(), desc(), offset(), limit(), where(id > last_id)
Python 版本: 3.11+
运行命令: uv run python examples/06_query_patterns/03_pagination_and_ordering.py  (从 mysql_lession/ 目录)
预期现象: 打印 offset/limit 分页的前 3 页，再打印 cursor 分页的前 3 页，最后对比两种方案
生产提醒: offset 分页在大偏移量时性能急剧下降(需全表扫描跳过行)；cursor 分页依赖有序唯一列，适合无限滚动场景
"""

import asyncio
from datetime import datetime, timedelta
from random import randint, seed

from sqlalchemy import Integer, String, DateTime, select, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"

seed(42)  # 固定随机种子，保证可复现


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "ex06_03_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    views: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"Post(id={self.id}, title={self.title!r}, views={self.views})"


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


PAGE_SIZE = 5


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # 插入 50 条示例数据
    base_time = datetime(2024, 1, 1)
    posts = [
        Post(
            title=f"文章_{i:03d}",
            created_at=base_time + timedelta(hours=i * 3),
            views=randint(10, 5000),
        )
        for i in range(1, 51)
    ]
    async with AsyncSession(engine) as session, session.begin():
        session.add_all(posts)

    async with AsyncSession(engine) as session:
        # ── 1. order_by 排序 ──
        print_section("1. order_by() — 升序 / 降序")

        print(f"\n▸ 按 views 降序 (前 {PAGE_SIZE} 条):")
        stmt = select(Post).order_by(desc(Post.views)).limit(PAGE_SIZE)
        rows = (await session.execute(stmt)).scalars().all()
        for p in rows:
            print(f"  {p}")

        print(f"\n▸ 按 created_at 升序 (前 {PAGE_SIZE} 条):")
        stmt = select(Post).order_by(asc(Post.created_at)).limit(PAGE_SIZE)
        rows = (await session.execute(stmt)).scalars().all()
        for p in rows:
            print(f"  {p}")

        # ── 2. offset/limit 传统分页 ──
        print_section("2. offset/limit 传统分页")
        for page in range(1, 4):
            offset_val = (page - 1) * PAGE_SIZE
            stmt = (
                select(Post)
                .order_by(asc(Post.id))
                .offset(offset_val)
                .limit(PAGE_SIZE)
            )
            rows = (await session.execute(stmt)).scalars().all()
            print(f"\n▸ 第 {page} 页 (offset={offset_val}, limit={PAGE_SIZE}):")
            for p in rows:
                print(f"  {p}")

        # ── 3. cursor 分页 ──
        print_section("3. cursor 分页 (基于 id)")
        print("  原理: WHERE id > last_id ORDER BY id LIMIT page_size")
        print("  优势: 无论翻到第几页，性能恒定 (走索引范围扫描)")

        last_id = 0  # 初始游标
        for page in range(1, 4):
            stmt = (
                select(Post)
                .where(Post.id > last_id)
                .order_by(asc(Post.id))
                .limit(PAGE_SIZE)
            )
            rows = (await session.execute(stmt)).scalars().all()
            print(f"\n▸ 第 {page} 页 (cursor: id > {last_id}):")
            for p in rows:
                print(f"  {p}")
            if rows:
                last_id = rows[-1].id  # 更新游标为本页最后一条的 id

        # ── 4. 对比总结 ──
        print_section("4. 两种分页方式对比")
        print("""
  ┌──────────────┬──────────────────────────┬──────────────────────────┐
  │              │  offset/limit 分页        │  cursor 分页              │
  ├──────────────┼──────────────────────────┼──────────────────────────┤
  │ SQL          │ LIMIT 10 OFFSET 10000    │ WHERE id>100 LIMIT 10    │
  │ 性能         │ offset 越大越慢           │ 恒定 O(page_size)        │
  │ 跳页         │ ✅ 支持任意跳页           │ ❌ 只能顺序翻页           │
  │ 数据一致性    │ 插入/删除会导致重复或遗漏  │ 不会重复或遗漏            │
  │ 适用场景      │ 后台管理、数据量小        │ 无限滚动、大数据量        │
  └──────────────┴──────────────────────────┴──────────────────────────┘
""")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("✅ 分页与排序演示完毕，表已清理。")


if __name__ == "__main__":
    asyncio.run(main())
