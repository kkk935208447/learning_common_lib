"""
目标: 演示乐观锁的完整教学链路 — 创建基线快照 → 显式 expected_version 更新 →
    跨请求并发冲突 → Session 同步陷阱 → 正确复现旧版本冲突 → 重试策略
关键 API: VersionMixin, SoftDeleteMixin, VersionedRepository, OptimisticLockError
Python 版本: 3.11+
运行命令: uv run python examples/08_repository_pattern/04_optimistic_lock.py  (从 mysql_lession/ 目录)
预期现象:
    1. 正常更新时 version 连续递增；
    2. 两个请求读取同一旧版本时，先提交者成功、后提交者抛出 OptimisticLockError；
    3. 同一 Session 的 Core UPDATE 会默认同步 ORM 对象，导致“伪旧版本”陷阱；
    4. 关闭 synchronize_session 后可正确复现旧版本冲突；
    5. 重试阶段会先失败一次，再在新事务中读取最新版本后成功
生产提醒: 乐观锁适合读多写少的场景；高并发写入场景考虑悲观锁（SELECT FOR UPDATE）；
    expected_version 应来自客户端或上一次读取快照；重试次数应有上限，重试间隔建议加随机抖动（jitter）
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import Integer, String, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

try:
    from ...templates.base_model import Base, TimestampMixin
    from ...templates.base_repository import VersionedRepository
    from ...templates.error_base import OptimisticLockError
    from ...templates.mixins import SoftDeleteMixin, VersionMixin
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from templates.base_model import Base, TimestampMixin
    from templates.base_repository import VersionedRepository
    from templates.error_base import OptimisticLockError
    from templates.mixins import SoftDeleteMixin, VersionMixin

DATABASE_URL = "mysql+asyncmy://root:123456@localhost:3306/tutorial_db"
ProductSnapshot = dict[str, int | str]


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


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def snapshot_from_product(product: Product) -> ProductSnapshot:
    return {
        "id": product.id,
        "name": product.name,
        "stock": product.stock,
        "price": product.price,
        "version": product.version,
    }


def format_snapshot(snapshot: ProductSnapshot | None) -> str:
    if snapshot is None:
        return "<记录不存在>"
    parts = [
        f"id={snapshot['id']}",
        f"name={snapshot['name']}",
        f"stock={snapshot['stock']}",
        f"price={snapshot['price']}",
        f"version={snapshot['version']}",
    ]
    return ", ".join(parts)


def describe_product(product: Product) -> str:
    return format_snapshot(snapshot_from_product(product))


async def fetch_latest_snapshot(
    factory: async_sessionmaker[AsyncSession],
    product_id: int,
) -> ProductSnapshot | None:
    async with factory() as session:
        product = await session.get(Product, product_id)
        if product is None:
            return None
        return snapshot_from_product(product)


async def print_latest_snapshot(
    factory: async_sessionmaker[AsyncSession],
    product_id: int,
    label: str,
) -> None:
    snapshot = await fetch_latest_snapshot(factory, product_id)
    print(f"  {label}: {format_snapshot(snapshot)}")


async def simulate_competing_writer(
    factory: async_sessionmaker[AsyncSession],
    product_id: int,
    *,
    stock: int,
) -> ProductSnapshot:
    """用独立 Session 模拟另一个请求抢先提交。"""
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            current = await repo.get_by_id(product_id, strict=True)
            expected_version = current.version
            print(
                f"      外部写者读取: {describe_product(current)} "
                f"(expected_version={expected_version})"
            )
            updated = await repo.update(
                product_id,
                expected_version=expected_version,
                stock=stock,
            )
            print(f"      外部写者提交成功: {describe_product(updated)}")
            return snapshot_from_product(updated)


async def update_with_retry(
    factory: async_sessionmaker[AsyncSession],
    product_id: int,
    *,
    max_retries: int = 3,
    inject_conflict_once: bool = True,
    **kwargs,
) -> Product | None:
    """每次重试都重新开启事务并重新读取最新 version。"""
    conflict_injected = False

    for attempt in range(1, max_retries + 1):
        try:
            async with factory() as session:
                async with session.begin():
                    repo = ProductRepository(session)
                    current = await repo.get_by_id(product_id, strict=True)
                    expected_version = current.version
                    print(f"  第 {attempt} 次尝试: 读取快照 -> {describe_product(current)}")
                    print(
                        f"    准备提交: expected_version={expected_version}, "
                        f"changes={kwargs}"
                    )

                    if inject_conflict_once and not conflict_injected:
                        print("    在本次提交前，模拟另一个事务抢先写入...")
                        await simulate_competing_writer(
                            factory,
                            product_id,
                            stock=current.stock - 5,
                        )
                        conflict_injected = True

                    updated = await repo.update(
                        product_id,
                        expected_version=expected_version,
                        **kwargs,
                    )
                    print(f"    提交成功: {describe_product(updated)}")
                    return updated
        except OptimisticLockError as exc:
            print(f"    提交失败: {exc.detail}")
            await print_latest_snapshot(factory, product_id, f"第 {attempt} 次失败后的数据库快照")
            if attempt == max_retries:
                raise
            print("    重新开启新事务，读取最新版本后再试。")
    return None


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    product_id = 0

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    print("=" * 60)
    print("  乐观锁教学演示：版本快照、冲突检测与重试")
    print("=" * 60)
    print("  乐观锁不是阻塞式数据库锁，而是提交时校验 version 是否仍然匹配。")

    # ── 1. 创建产品并建立基线快照 ──────────────────────
    print_section("1. 基线状态：创建产品，确认初始 version")
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            product = await repo.create(Product(name="机械键盘", stock=100, price=59900))
            product_id = product.id
            print(f"  ORM 对象: {describe_product(product)}")
            print("  新记录初始 version=1，后续每次成功更新都会递增。")
    await print_latest_snapshot(factory, product_id, "数据库快照")

    # ── 2. 正常更新：显式 expected_version ─────────────
    print_section("2. 正常更新：expected_version 驱动 version 自增")
    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            current = await repo.get_by_id(product_id, strict=True)
            expected_version = current.version
            print(f"  第一次更新前: {describe_product(current)}")
            print(
                f"  提交条件: WHERE id={product_id} AND version={expected_version}; "
                f"SET stock=90, version={expected_version + 1}"
            )
            updated = await repo.update(product_id, expected_version=expected_version, stock=90)
            print(f"  第一次更新后: {describe_product(updated)}")
    await print_latest_snapshot(factory, product_id, "第一次提交后的数据库快照")

    async with factory() as session:
        async with session.begin():
            repo = ProductRepository(session)
            current = await repo.get_by_id(product_id, strict=True)
            expected_version = current.version
            print(f"  第二次更新前: {describe_product(current)}")
            print(
                f"  提交条件: WHERE id={product_id} AND version={expected_version}; "
                f"SET price=49900, version={expected_version + 1}"
            )
            updated = await repo.update(product_id, expected_version=expected_version, price=49900)
            print(f"  第二次更新后: {describe_product(updated)}")
    await print_latest_snapshot(factory, product_id, "第二次提交后的数据库快照")

    # ── 3. 跨请求并发冲突 ─────────────────────────────
    print_section("3. 跨请求并发冲突：两个请求读取同一旧版本")
    async with factory() as session_a, factory() as session_b:
        repo_a = ProductRepository(session_a)
        repo_b = ProductRepository(session_b)

        async with session_a.begin():
            product_a = await repo_a.get_by_id(product_id, strict=True)
            version_a = product_a.version
            print(f"  用户A 读取: {describe_product(product_a)}")

        async with session_b.begin():
            product_b = await repo_b.get_by_id(product_id, strict=True)
            version_b = product_b.version
            print(f"  用户B 读取: {describe_product(product_b)}")

        print("  两个请求都拿到 version=3；谁先提交，谁就占用 version=3 -> 4 这次更新资格。")

        async with session_a.begin():
            updated_a = await repo_a.update(product_id, expected_version=version_a, stock=80)
            print(
                f"  用户A 提交: expected_version={version_a} -> 成功, "
                f"{describe_product(updated_a)}"
            )
        await print_latest_snapshot(factory, product_id, "A 提交后的数据库快照")

        async with session_b.begin():
            try:
                await repo_b.update(product_id, expected_version=version_b, stock=70)
            except OptimisticLockError as exc:
                print(f"  用户B 提交: expected_version={version_b} -> 失败")
                print(f"    异常 detail: {exc.detail}")
        await print_latest_snapshot(factory, product_id, "B 失败后的数据库快照")

    # ── 4. Session 同步陷阱 + 正确复现 ────────────────
    print_section("4. Session 同步陷阱：为什么“伪旧版本”不会触发冲突")
    async with factory() as session:
        repo = ProductRepository(session)
        async with session.begin():
            product = await repo.get_by_id(product_id, strict=True)
            print(f"  当前已提交基线: {describe_product(product)}")

            trap_savepoint = await session.begin_nested()
            try:
                before_sync_version = product.version
                print(f"  先保存 before_sync_version={before_sync_version}")
                result = await session.execute(
                    sa_update(Product)
                    .where(Product.id == product_id)
                    .values(stock=60, version=before_sync_version + 1)
                )
                print(f"  同一 Session 执行 Core UPDATE, rowcount={result.rowcount}")
                print(f"  ORM 对象被默认同步后: {describe_product(product)}")
                print("  如果此时再把 product.version 当作旧版本，它其实已经是新版本了。")
            finally:
                await trap_savepoint.rollback()
                await session.refresh(product)
            print(f"  回滚陷阱演示后恢复基线: {describe_product(product)}")

            real_conflict_savepoint = await session.begin_nested()
            try:
                stale_version = product.version
                print(f"  正确复现前先保存 stale_version={stale_version}")
                result = await session.execute(
                    sa_update(Product)
                    .where(Product.id == product_id)
                    .values(stock=60, version=stale_version + 1)
                    .execution_options(synchronize_session=False)
                )
                print(f"  关闭 Session 同步后手动前移版本, rowcount={result.rowcount}")
                print(f"  ORM 对象仍保留旧快照: {describe_product(product)}")

                try:
                    await repo.update(product_id, expected_version=stale_version, stock=50)
                except OptimisticLockError as exc:
                    print(f"  使用 stale_version={stale_version} 再提交 -> 触发 OptimisticLockError")
                    print(f"    异常 detail: {exc.detail}")
                    await session.refresh(product)
                    print(f"  refresh 后对象追上数据库: {describe_product(product)}")
            finally:
                await real_conflict_savepoint.rollback()
                await session.refresh(product)
            print(f"  回滚教学事务后恢复基线: {describe_product(product)}")
    await print_latest_snapshot(factory, product_id, "第 4 阶段结束后的数据库快照")

    # ── 5. 重试策略 ───────────────────────────────────
    print_section("5. 重试策略：失败后在新事务里重新读取最新版本")
    await update_with_retry(factory, product_id, stock=40)
    await print_latest_snapshot(factory, product_id, "重试成功后的数据库快照")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n  ✅ 乐观锁演示完成!")


if __name__ == "__main__":
    asyncio.run(main())
