"""
目标: 演示软删除的完整生命周期 — 创建 → 软删除 → 查询过滤 → 恢复 → 物理删除
关键 API: SoftDeleteMixin, SoftDeleteRepository, delete/restore/hard_delete/list_deleted
Python 版本: 3.11+
运行命令: uv run python examples/08_repository_pattern/03_soft_delete.py  (从 mysql_lession/ 目录)
预期现象: 依次演示软删除标记、自动过滤、已删除列表查询、恢复、物理删除，打印每步的记录状态
生产提醒: 软删除保留审计轨迹，但会增加查询复杂度（所有查询需过滤 is_deleted）；
    长期积累的软删除数据建议定期归档到历史表；索引应包含 is_deleted 字段以避免全表扫描
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import String, Integer, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

# 支持直接运行和包导入两种方式
try:
    from ...templates.base_model import Base, TimestampMixin
    from ...templates.mixins import SoftDeleteMixin
    from ...templates.base_repository import SoftDeleteRepository
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from templates.base_model import Base, TimestampMixin
    from templates.mixins import SoftDeleteMixin
    from templates.base_repository import SoftDeleteRepository

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


# ── 模型定义 ──────────────────────────────────────────────
class Article(SoftDeleteMixin, TimestampMixin, Base):
    """文章模型，带软删除支持。"""
    __tablename__ = "ex08_03_article"

    title: Mapped[str] = mapped_column(String(200), comment="标题")
    content: Mapped[str] = mapped_column(String(1000), default="", comment="内容")
    author: Mapped[str] = mapped_column(String(50), comment="作者")


class ArticleRepository(SoftDeleteRepository["Article"]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Article)


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # ── 1. 创建文章 ──────────────────────────────────────
    print("=" * 60)
    print("  软删除完整生命周期演示")
    print("=" * 60)

    async with factory() as session:
        async with session.begin():
            repo = ArticleRepository(session)
            a1 = await repo.create(Article(title="Python 异步编程", content="async/await 入门", author="张三"))
            a2 = await repo.create(Article(title="SQLAlchemy ORM", content="企业级 ORM 实践", author="李四"))
            a3 = await repo.create(Article(title="FastAPI 教程", content="高性能 API 框架", author="张三"))
            print(f"\n▸ 创建 3 篇文章")
            print(f"  总数: {await repo.count()}")
            for a in await repo.list_all():
                print(f"    [{a.id}] {a.title} by {a.author} (is_deleted={a.is_deleted})")

    # ── 2. 软删除 ────────────────────────────────────────
    async with factory() as session:
        async with session.begin():
            repo = ArticleRepository(session)
            await repo.delete(a1.id)
            await repo.delete(a2.id)
            print(f"\n▸ 软删除文章 #{a1.id} 和 #{a2.id}")
            print(f"  未删除数量: {await repo.count()}")

            # list_all 自动过滤已删除
            active = await repo.list_all()
            print(f"  list_all() 结果 (自动过滤已删除):")
            for a in active:
                print(f"    [{a.id}] {a.title}")

            # list_deleted 查询已删除
            deleted = await repo.list_deleted()
            print(f"  list_deleted() 结果:")
            for a in deleted:
                print(f"    [{a.id}] {a.title} (deleted_at={a.deleted_at})")

    # ── 3. 对比软删除 vs 物理删除的 SQL ──────────────────
    print(f"\n▸ 软删除 vs 物理删除 SQL 对比")
    print(f"  软删除: UPDATE article SET is_deleted=1, deleted_at=NOW() WHERE id=?")
    print(f"  物理删除: DELETE FROM article WHERE id=?")

    # ── 4. 恢复软删除记录 ────────────────────────────────
    async with factory() as session:
        async with session.begin():
            repo = ArticleRepository(session)
            restored = await repo.restore(a1.id)
            print(f"\n▸ 恢复文章 #{a1.id}: {restored.title}")
            print(f"  is_deleted={restored.is_deleted}, deleted_at={restored.deleted_at}")
            print(f"  未删除数量: {await repo.count()}")

    # ── 5. 物理删除 ──────────────────────────────────────
    async with factory() as session:
        async with session.begin():
            repo = ArticleRepository(session)
            await repo.hard_delete(a2.id)
            print(f"\n▸ 物理删除文章 #{a2.id}")

            # 验证：物理删除后 list_deleted 也查不到了
            deleted = await repo.list_deleted()
            print(f"  已删除列表 (物理删除后): {[a.title for a in deleted]}")

            # 验证：用原始 SQL 确认记录已不存在
            result = await session.execute(select(Article).where(Article.id == a2.id))
            print(f"  直接查询 #{a2.id}: {result.scalars().first()}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print(f"\n  ✅ 软删除演示完成!")


if __name__ == "__main__":
    asyncio.run(main())
