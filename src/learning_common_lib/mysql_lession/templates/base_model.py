"""
解决什么问题: 模型公共字段（id、created_at、updated_at）重复定义问题
输入输出约定: 继承 Base 获得自动表名生成，混入 TimestampMixin 获得公共字段
失败策略: 表名冲突由数据库层面报错；字段类型不匹配由 SQLAlchemy 映射时抛出异常
不适用场景: 无主键或使用 UUID 主键的模型（需自行定义主键字段）
"""

import re
import asyncio
from datetime import datetime

from sqlalchemy import Integer, DateTime, MetaData, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# 统一约束命名规范 — 让数据库生成的约束名可预测，便于 Alembic 迁移管理
# 不设置的话，数据库会生成随机约束名，迁移脚本无法正确识别和比对
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",              # 普通索引
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # 唯一约束
    "ck": "ck_%(table_name)s_%(constraint_name)s", # CHECK 约束
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",  # 外键
    "pk": "pk_%(table_name)s",                  # 主键
}


class Base(AsyncAttrs, DeclarativeBase):
    """
    声明式基类，所有模型继承此类。

    自动将 CamelCase 类名转换为 snake_case 表名。
    例如: UserProfile → user_profile

    同时继承 AsyncAttrs，模型会具备 awaitable_attrs 能力。
    这能让关系属性在异步里显式 await 加载，但企业代码仍推荐：
    relationship(..., lazy="raise") + 查询时 selectinload/joinedload 显式预加载。
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """将驼峰命名转换为下划线命名作为表名。"""
        # 在大写字母前插入下划线，然后转小写
        name = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", cls.__name__)
        return name.lower()


class TimestampMixin:
    """
    公共字段混入类。

    提供 id、created_at、updated_at 三个字段，
    所有业务模型通过多继承混入即可获得这些字段。
    """

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="主键ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),  # 由数据库生成默认值
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),  # 更新时自动刷新
        comment="更新时间",
    )


async def _demo() -> None:
    """演示：定义示例模型，建表、插入、查询、删表。"""
    from sqlalchemy import String
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    # 定义示例模型
    class SampleItem(TimestampMixin, Base):
        """示例模型，自动表名为 sample_item。"""
        name: Mapped[str] = mapped_column(String(100), comment="名称")

    print(f"自动生成的表名: {SampleItem.__tablename__}")

    # 创建引擎和表
    engine = create_async_engine(
        "mysql+asyncmy://root:123456@localhost:3306/tutorial_db",
        echo=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("表创建成功")

    # 插入数据
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = SampleItem(name="测试项目")
        session.add(item)
        await session.commit()
        # server_default 字段需要 refresh 才能从数据库加载
        await session.refresh(item)
        print(f"插入成功 - id: {item.id}, name: {item.name}, created_at: {item.created_at}")

    # 查询数据
    async with factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(SampleItem))
        items = result.scalars().all()
        for i in items:
            print(f"查询结果 - id: {i.id}, name: {i.name}")

    # 删除表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("表已删除")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_demo())
