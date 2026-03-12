"""
解决什么问题: CRUD 操作重复编写问题 + SQLAlchemy 异常泄漏问题 + 软删除/乐观锁企业级需求
输入输出约定: 泛型仓储接收 AsyncSession 和模型类型，提供标准 CRUD 方法；异常统一转换为业务异常
失败策略: 查询不到 → NotFoundError（strict 模式）或 None；唯一约束冲突 → DuplicateError；乐观锁冲突 → OptimisticLockError
不适用场景: 复杂联表查询、聚合统计等场景（需自行编写查询逻辑）

继承链（按需选择层级）:
  BaseRepository        — 基础 CRUD + 异常转换
  SoftDeleteRepository  — 继承 BaseRepository，delete→软删除，list_all→自动过滤
  VersionedRepository   — 继承 SoftDeleteRepository，update 时自动检查乐观锁
"""

import asyncio
from datetime import datetime
from typing import TypeVar, Generic

from sqlalchemy import select, update as sa_update, func as sa_func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .base_model import Base
    from .error_base import (
        NotFoundError, DuplicateError, DatabaseError,
        OptimisticLockError, AppError,
    )
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.base_model import Base  # type: ignore[no-redef]
    from templates.error_base import (  # type: ignore[no-redef]
        NotFoundError, DuplicateError, DatabaseError,
        OptimisticLockError, AppError,
    )

# 泛型类型变量，约束为 Base 的子类
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    泛型 CRUD 仓储基类。

    所有数据库操作都包裹 try/except，将 SQLAlchemy 异常转换为业务异常：
    - IntegrityError → DuplicateError（唯一约束冲突）
    - SQLAlchemyError → DatabaseError（其他数据库错误）

    用法:
        repo = BaseRepository(session, User)
        user = await repo.create(User(name="张三"))
        user = await repo.get_by_id(1)
    """

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: int, *, strict: bool = False) -> T | None:
        """根据主键 ID 查询单条记录。

        strict=True 时，不存在则抛出 NotFoundError。
        """
        try:
            obj = await self.session.get(self.model, id)
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e
        if obj is None and strict:
            raise NotFoundError(
                detail={"resource": self.model.__name__, "id": id},
            )
        return obj

    async def list_all(self, offset: int = 0, limit: int = 100) -> list[T]:
        """分页查询所有记录。"""
        try:
            stmt = select(self.model).offset(offset).limit(limit)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e

    async def create(self, obj: T, *, refresh: bool = True) -> T:
        """
        新增一条记录并返回。

        refresh=True（默认）会多一次 SELECT 往返以加载 server_default 字段。
        IntegrityError（唯一约束冲突）自动转换为 DuplicateError。
        """
        try:
            self.session.add(obj)
            await self.session.flush()
            if refresh:
                await self.session.refresh(obj)
            return obj
        except IntegrityError as e:
            raise DuplicateError(
                message="资源已存在（唯一约束冲突）",
                detail={"model": self.model.__name__},
                internal_message=str(e),
            ) from e
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e

    async def update(self, id: int, *, refresh: bool = True, strict: bool = False, **kwargs) -> T | None:
        """
        根据 ID 更新记录，返回更新后的对象。

        strict=True 时，不存在则抛出 NotFoundError。
        refresh 参数含义同 create。
        """
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return None
        try:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            await self.session.flush()
            if refresh:
                await self.session.refresh(obj)
            return obj
        except IntegrityError as e:
            raise DuplicateError(
                detail={"model": self.model.__name__, "id": id},
                internal_message=str(e),
            ) from e
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e

    async def delete(self, id: int, *, strict: bool = False) -> bool:
        """根据 ID 删除记录。strict=True 时不存在则抛出 NotFoundError。"""
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return False
        try:
            await self.session.delete(obj)
            await self.session.flush()
            return True
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e

    async def count(self) -> int:
        """统计当前模型的总记录数。"""
        try:
            stmt = select(sa_func.count()).select_from(self.model)
            result = await self.session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e


class SoftDeleteRepository(BaseRepository[T]):
    """继承 BaseRepository，覆写 delete→软删除，list_all→自动过滤已删除记录。

    要求模型混入 SoftDeleteMixin（提供 is_deleted、deleted_at 字段）。

    用法:
        repo = SoftDeleteRepository(session, Article)
        await repo.delete(1)          # 软删除（标记 is_deleted=True）
        await repo.list_all()         # 自动过滤已删除
        await repo.restore(1)         # 恢复软删除记录
        await repo.hard_delete(1)     # 物理删除
        await repo.list_deleted()     # 查询已删除记录
    """

    async def list_all(self, offset: int = 0, limit: int = 100) -> list[T]:
        """分页查询所有未删除记录。"""
        try:
            stmt = (
                select(self.model)
                .where(self.model.is_deleted == False)  # noqa: E712
                .offset(offset)
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e

    async def delete(self, id: int, *, strict: bool = False) -> bool:
        """软删除：标记 is_deleted=True, deleted_at=now()。"""
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return False
        try:
            obj.is_deleted = True
            obj.deleted_at = datetime.now()
            await self.session.flush()
            return True
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e

    async def restore(self, id: int) -> T:
        """恢复软删除记录。不存在则抛出 NotFoundError。"""
        obj = await self.get_by_id(id, strict=True)
        if not getattr(obj, "is_deleted", False):
            raise NotFoundError(
                message="记录未被删除，无需恢复",
                detail={"resource": self.model.__name__, "id": id},
            )
        try:
            obj.is_deleted = False
            obj.deleted_at = None
            await self.session.flush()
            await self.session.refresh(obj)
            return obj
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e

    async def hard_delete(self, id: int, *, strict: bool = False) -> bool:
        """物理删除：真正从数据库中移除记录。"""
        return await super().delete(id, strict=strict)

    async def list_deleted(self, offset: int = 0, limit: int = 100) -> list[T]:
        """查询已软删除的记录。"""
        try:
            stmt = (
                select(self.model)
                .where(self.model.is_deleted == True)  # noqa: E712
                .offset(offset)
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e

    async def count(self) -> int:
        """统计未删除记录数。"""
        try:
            stmt = (
                select(sa_func.count())
                .select_from(self.model)
                .where(self.model.is_deleted == False)  # noqa: E712
            )
            result = await self.session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__},
            ) from e


class VersionedRepository(SoftDeleteRepository[T]):
    """继承 SoftDeleteRepository，update 时自动检查 version 乐观锁。

    要求模型混入 VersionMixin（提供 version 字段）。
    更新时 WHERE version = current_version, SET version = version + 1。
    版本不匹配 → raise OptimisticLockError。

    用法:
        repo = VersionedRepository(session, Product)
        product = await repo.update(1, stock=90)  # 自动检查并递增 version
    """

    async def update(self, id: int, *, refresh: bool = True, strict: bool = False, **kwargs) -> T | None:
        """乐观锁更新：WHERE version = current_version, SET version = version + 1。"""
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return None
        current_version = obj.version
        try:
            values = {**kwargs, "version": current_version + 1}
            stmt = (
                sa_update(self.model)
                .where(self.model.id == id, self.model.version == current_version)
                .values(**values)
            )
            result = await self.session.execute(stmt)
            if result.rowcount == 0:
                raise OptimisticLockError(
                    detail={
                        "resource": self.model.__name__,
                        "id": id,
                        "expected_version": current_version,
                    },
                )
            # 刷新 ORM 对象以反映数据库中的最新状态
            await self.session.refresh(obj)
            return obj
        except AppError:
            raise
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e


async def _demo() -> None:
    """演示：BaseRepository CRUD + 异常转换 + SoftDeleteRepository + VersionedRepository。"""
    from sqlalchemy import String, Integer
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    try:
        from .base_model import TimestampMixin
        from .mixins import SoftDeleteMixin, VersionMixin
    except ImportError:
        from templates.base_model import TimestampMixin  # type: ignore[no-redef]
        from templates.mixins import SoftDeleteMixin, VersionMixin  # type: ignore[no-redef]

    # 定义模型
    class User(TimestampMixin, Base):
        """用户模型（基础 CRUD 演示）。"""
        name: Mapped[str] = mapped_column(String(50), comment="用户名")
        email: Mapped[str] = mapped_column(String(100), unique=True, comment="邮箱")

    class Article(SoftDeleteMixin, TimestampMixin, Base):
        """文章模型（软删除演示）。"""
        title: Mapped[str] = mapped_column(String(200), comment="标题")

    class Product(VersionMixin, SoftDeleteMixin, TimestampMixin, Base):
        """产品模型（乐观锁演示）。"""
        name: Mapped[str] = mapped_column(String(100), comment="产品名")
        stock: Mapped[int] = mapped_column(Integer, default=0, comment="库存")

    engine = create_async_engine(
        "mysql+asyncmy://root:123456@localhost:3306/tutorial_db",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. BaseRepository — 基础 CRUD + 异常转换
    print("=== BaseRepository CRUD ===")
    async with factory() as session:
        async with session.begin():
            repo = BaseRepository(session, User)
            user = await repo.create(User(name="张三", email="zhangsan@example.com"))
            print(f"  创建: id={user.id}, name={user.name}")

            found = await repo.get_by_id(user.id)
            print(f"  查询: name={found.name}")

            updated = await repo.update(user.id, name="李四")
            print(f"  更新: name={updated.name}")

            total = await repo.count()
            print(f"  总数: {total}")

            # 演示 strict 模式
            try:
                await repo.get_by_id(999, strict=True)
            except NotFoundError as e:
                print(f"  strict 模式: {e}")

            # 演示 DuplicateError
            try:
                await repo.create(User(name="王五", email="zhangsan@example.com"))
            except DuplicateError as e:
                print(f"  唯一约束冲突: {e}")

    # 2. SoftDeleteRepository — 软删除
    print("\n=== SoftDeleteRepository ===")
    async with factory() as session:
        async with session.begin():
            repo = SoftDeleteRepository(session, Article)
            a1 = await repo.create(Article(title="Python 入门"))
            a2 = await repo.create(Article(title="SQLAlchemy 进阶"))
            print(f"  创建 2 篇文章, count={await repo.count()}")

            await repo.delete(a1.id)
            print(f"  软删除后 count={await repo.count()}")
            print(f"  已删除列表: {[a.title for a in await repo.list_deleted()]}")

            restored = await repo.restore(a1.id)
            print(f"  恢复后 count={await repo.count()}, restored={restored.title}")

    # 3. VersionedRepository — 乐观锁
    print("\n=== VersionedRepository ===")
    async with factory() as session:
        async with session.begin():
            repo = VersionedRepository(session, Product)
            p = await repo.create(Product(name="键盘", stock=100))
            print(f"  创建: name={p.name}, version={p.version}")

            p = await repo.update(p.id, stock=90)
            print(f"  更新: stock={p.stock}, version={p.version}")

    # 模拟乐观锁冲突
    async with factory() as session1, factory() as session2:
        async with session1.begin():
            repo1 = VersionedRepository(session1, Product)
            p1 = await repo1.get_by_id(1)
            print(f"\n  用户A 读取: version={p1.version}")
            p1 = await repo1.update(p1.id, stock=80)
            print(f"  用户A 更新成功: stock={p1.stock}, version={p1.version}")

        async with session2.begin():
            repo2 = VersionedRepository(session2, Product)
            p2 = await repo2.get_by_id(1)
            # p2.version 此时已经是 3（被 session1 更新过），但如果是真正并发场景
            # 两个 session 同时读到 version=2，其中一个会失败
            print(f"  用户B 读取: version={p2.version}, stock={p2.stock}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\nRepository 演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
