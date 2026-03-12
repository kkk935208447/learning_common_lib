"""
目标: 演示乐观锁冲突检测 — 创建 → 正常更新(version自增) → 模拟并发冲突 → 捕获 OptimisticLockError → 重试策略
关键 API: VersionMixin, SoftDeleteMixin, VersionedRepository, OptimisticLockError
Python 版本: 3.11+
运行命令: uv run python examples/08_repository_pattern/04_optimistic_lock.py  (从 mysql_lession/ 目录)
预期现象: 正常更新成功并 version 自增；模拟并发冲突时捕获 OptimisticLockError；重试策略演示成功
生产提醒: 乐观锁适合读多写少的场景；高并发写入场景考虑悲观锁（SELECT FOR UPDATE）；
    重试次数应有上限，避免无限重试；重试间隔建议加随机抖动（jitter）
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import String, Integer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

try:
    from ...templates.base_model import Base, TimestampMixin
    from ...templates.mixins import SoftDeleteMixin, VersionMixin
    from ...templates.base_repository import VersionedRepository
    from ...templates.error_base import OptimisticLockError
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from templates.base_model import Base, TimestampMixin
    from templates.mixins import SoftDeleteMixin, VersionMixin
    from templates.base_repository import VersionedRepository
    from templates.error_base import OptimisticLockError

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"


# ── 模型定义 ──────────────────────────────────────────────
class Product(VersionMixin, SoftDeleteMixin, TimestampMixin, Base):
    """产品模型，带乐观锁 + 软删除支持。"""
    __tablename__ = "ex08_04_product"

    name: Mapped[str] = mapped_column(String(100), comment="产品名称")
    stock: Mapped[int] = mapped_column(Integer, default=0, comment="库存数量")
    price: Mapped[int] = mapped_column(Integer, default=0, comment="价格(分)")


class ProductRepository(VersionedRepository["Product"]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    print("=" * 60)
    print("  乐观锁冲突检测演示")
    print("=" * 60)

    # ── 1. 创建产品 ──────────────────────────────────────
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            p = await repo.create(Product(name="机械键盘", stock=100, price=59900))
            print(f"\n▸ 创建产品: name={p.name}, stock={p.stock}, version={p.version}")

    # ── 2. 正常更新（version 自增）─────────────────────
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            p = await repo.update(1, stock=90)
            print(f"\n▸ 正常更新: stock={p.stock}, version={p.version} (自增)")

            p = await repo.update(1, price=49900)
            print(f"  再次更新: price={p.price}, version={p.version} (再次自增)")

    # ── 3. 模拟并发冲突 ─────────────────────────────────
    print(f"\n▸ 模拟并发冲突:")

    # 用户 A 和用户 B 同时读取同一条记录
    async with factory() as session_a, factory() as session_b:
        # 用户 A 读取
        async with session_a.begin():
            repo_a = ProductRepository(session_a)
            product_a = await repo_a.get_by_id(1)
            version_a = product_a.version
            print(f"  用户A 读取: stock={product_a.stock}, version={version_a}")

            # 用户 A 先更新成功
            product_a = await repo_a.update(1, stock=80)
            print(f"  用户A 更新成功: stock={product_a.stock}, version={product_a.version}")

        # 用户 B 后读取（此时 version 已经变了）
        async with session_b.begin():
            repo_b = ProductRepository(session_b)
            product_b = await repo_b.get_by_id(1)
            print(f"  用户B 读取: stock={product_b.stock}, version={product_b.version}")

            # 用户 B 正常更新（因为读到的是最新 version）
            product_b = await repo_b.update(1, stock=70)
            print(f"  用户B 更新成功: stock={product_b.stock}, version={product_b.version}")

    # ── 4. 真正的冲突场景：手动模拟旧 version 更新 ─────
    print(f"\n▸ 手动模拟旧 version 冲突:")
    from sqlalchemy import update as sa_update
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            p = await repo.get_by_id(1)
            print(f"  当前: stock={p.stock}, version={p.version}")

            # 先把 version 回退（模拟另一个事务已经更新过）
            await session.execute(
                sa_update(Product)
                .where(Product.id == 1)
                .values(version=p.version + 1, stock=60)
            )
            await session.flush()

            # 此时 repo 中缓存的 version 是旧的，更新会失败
            try:
                await repo.update(1, stock=50)
            except OptimisticLockError as e:
                print(f"  捕获 OptimisticLockError: {e}")
                print(f"    detail: {e.detail}")

    # ── 5. 重试策略演示 ─────────────────────────────────
    print(f"\n▸ 重试策略演示:")

    async def update_with_retry(factory, product_id: int, max_retries: int = 3, **kwargs):
        """读取最新版本后重试的标准模式。"""
        for attempt in range(1, max_retries + 1):
            async with factory() as session:
                async with session.begin():
                    repo = ProductRepository(session)
                    try:
                        result = await repo.update(product_id, **kwargs)
                        print(f"    第 {attempt} 次尝试: 成功! stock={result.stock}, version={result.version}")
                        return result
                    except OptimisticLockError:
                        print(f"    第 {attempt} 次尝试: 冲突，重新读取最新版本...")
                        if attempt == max_retries:
                            raise
        return None

    result = await update_with_retry(factory, 1, stock=40)

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print(f"\n  ✅ 乐观锁演示完成!")


if __name__ == "__main__":
    asyncio.run(main())
