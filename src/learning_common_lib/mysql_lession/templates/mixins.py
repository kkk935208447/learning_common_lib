"""
解决什么问题: 提供可选的软删除和乐观锁混入，与 base_model.py 的 TimestampMixin 同级使用
输入输出约定: 模型通过多继承混入 SoftDeleteMixin / VersionMixin 获得对应字段
失败策略: 字段类型不匹配由 SQLAlchemy 映射时抛出异常
不适用场景: 不需要软删除或乐观锁的简单模型（直接用 TimestampMixin + Base 即可）
"""

import asyncio
from datetime import datetime

from sqlalchemy import Integer, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeleteMixin:
    """软删除混入。

    提供 is_deleted 和 deleted_at 两个字段。
    配合 SoftDeleteRepository 使用，delete 操作只标记不物理删除，保留审计轨迹。

    用法:
        class Article(SoftDeleteMixin, TimestampMixin, Base):
            title: Mapped[str] = mapped_column(String(200))
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
        comment="是否已软删除",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="软删除时间",
    )


class VersionMixin:
    """乐观锁混入。

    提供 version 字段，每次更新时 version + 1。
    配合 VersionedRepository 使用，更新时检查 version 是否匹配，防止并发覆盖。

    用法:
        class Product(VersionMixin, SoftDeleteMixin, TimestampMixin, Base):
            name: Mapped[str] = mapped_column(String(100))
            stock: Mapped[int] = mapped_column(Integer, default=0)
    """

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="乐观锁版本号",
    )


async def _demo() -> None:
    """演示：定义带软删除和乐观锁的模型，建表、软删除标记/恢复、乐观锁冲突检测。"""
    from sqlalchemy import String, select, update
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    try:
        from .base_model import Base, TimestampMixin
    except ImportError:
        from templates.base_model import Base, TimestampMixin  # type: ignore[no-redef]

    # 定义带软删除 + 乐观锁的模型
    class DemoProduct(SoftDeleteMixin, VersionMixin, TimestampMixin, Base):
        """演示用产品模型。"""
        __tablename__ = "demo_mixin_product"
        name: Mapped[str] = mapped_column(String(100), comment="产品名称")
        stock: Mapped[int] = mapped_column(Integer, default=0, comment="库存")

    engine = create_async_engine(
        "mysql+asyncmy://root:123456@localhost:3306/tutorial_db",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. 软删除演示
    print("=== 软删除演示 ===")
    async with factory() as session:
        async with session.begin():
            product = DemoProduct(name="键盘", stock=100)
            session.add(product)
            await session.flush()
            await session.refresh(product)
            print(f"  创建: {product.name}, is_deleted={product.is_deleted}, version={product.version}")

            # 软删除：标记 is_deleted=True
            product.is_deleted = True
            product.deleted_at = datetime.now()
            await session.flush()
            await session.refresh(product)
            print(f"  软删除后: is_deleted={product.is_deleted}, deleted_at={product.deleted_at}")

            # 恢复
            product.is_deleted = False
            product.deleted_at = None
            await session.flush()
            await session.refresh(product)
            print(f"  恢复后: is_deleted={product.is_deleted}, deleted_at={product.deleted_at}")

    # 2. 乐观锁演示
    print("\n=== 乐观锁演示 ===")
    async with factory() as session:
        async with session.begin():
            p = await session.get(DemoProduct, 1)
            print(f"  当前 version={p.version}")

            # 正常更新：version 手动 +1
            old_version = p.version
            result = await session.execute(
                update(DemoProduct)
                .where(DemoProduct.id == p.id, DemoProduct.version == old_version)
                .values(stock=90, version=old_version + 1)
            )
            if result.rowcount == 1:
                print(f"  更新成功: stock=90, version={old_version + 1}")
            else:
                print(f"  乐观锁冲突! rowcount={result.rowcount}")

            # 模拟并发冲突：用旧 version 再次更新
            result = await session.execute(
                update(DemoProduct)
                .where(DemoProduct.id == p.id, DemoProduct.version == old_version)
                .values(stock=80, version=old_version + 1)
            )
            if result.rowcount == 0:
                print(f"  模拟冲突: 旧 version={old_version} 更新失败 (rowcount=0)")
            else:
                print(f"  意外成功: rowcount={result.rowcount}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\n混入演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
