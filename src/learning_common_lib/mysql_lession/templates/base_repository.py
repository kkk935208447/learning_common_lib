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

from sqlalchemy import inspect as sa_inspect, select, update as sa_update, func as sa_func
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from .base_model import Base
    from .error_base import (
        AppValidationError, NotFoundError, DuplicateError, DatabaseError,
        OptimisticLockError, AppError,
    )
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.base_model import Base  # type: ignore[no-redef]
    from templates.error_base import (  # type: ignore[no-redef]
        AppValidationError, NotFoundError, DuplicateError, DatabaseError,
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

    @staticmethod
    def _extract_dbapi_code(error: SQLAlchemyError) -> int | None:
        """提取底层 DBAPI/MySQL 错误码，用于细分异常类型。"""
        original = getattr(error, "orig", None)
        args = getattr(original, "args", ()) or getattr(error, "args", ())
        if not args:
            return None
        code = args[0]
        return code if isinstance(code, int) else None

    # * 表示 后面的参数必须用关键字方式传递（keyword-only），不能用位置参数传
    def _build_model_detail(self, *, id: int | None = None) -> dict[str, object]:
        detail: dict[str, object] = {"model": self.model.__name__}
        if id is not None:
            detail["id"] = id
        return detail

    def _mapped_column_keys(self) -> set[str]:
        mapper = sa_inspect(self.model)
        return {attr.key for attr in mapper.column_attrs}

    def _protected_update_fields(self) -> set[str]:
        """通用 update 默认禁止改写系统字段。"""
        # & 取两个集合的交集
        return {"id", "created_at", "updated_at"} & self._mapped_column_keys()

    def _validate_update_fields(self, kwargs: dict[str, object]) -> None:
        if not kwargs:
            raise AppValidationError(
                message="更新内容不能为空",
                detail={"model": self.model.__name__},
            )
        invalid_fields = sorted(set(kwargs) - self._mapped_column_keys())
        if invalid_fields:
            raise AppValidationError(
                message="存在未映射的更新字段",
                detail={
                    "model": self.model.__name__,
                    "invalid_fields": invalid_fields,
                },
            )
        protected_fields = sorted(set(kwargs) & self._protected_update_fields())
        if protected_fields:
            raise AppValidationError(
                message="存在不允许直接更新的系统字段",
                detail={
                    "model": self.model.__name__,
                    "protected_fields": protected_fields,
                },
            )

    def _apply_default_ordering(self, stmt):
        """分页查询默认按主键升序，避免无序分页带来的不稳定结果。"""
        if hasattr(self.model, "id"):
            return stmt.order_by(self.model.id.asc())
        return stmt

    def _map_integrity_error(
        self,
        error: IntegrityError,
        *,
        id: int | None = None,
    ) -> AppError:
        """按 MySQL 错误码细分 IntegrityError，避免全部误判为重复数据。"""
        mysql_code = self._extract_dbapi_code(error)
        detail = self._build_model_detail(id=id)
        internal_message = str(error)

        if mysql_code == 1062:
            return DuplicateError(
                message="资源已存在（唯一约束冲突）",
                detail=detail,
                internal_message=internal_message,
            )

        if mysql_code in {1048, 1451, 1452}:
            return AppValidationError(
                message="数据约束校验失败，请检查关联关系和必填字段",
                detail={**detail, "db_error_code": mysql_code},
                internal_message=internal_message,
            )

        return DatabaseError(
            detail={**detail, "db_error_code": mysql_code} if mysql_code is not None else detail,
            internal_message=internal_message,
            log_extra={"model": self.model.__name__, "id": id, "db_error_code": mysql_code},
        )

    def _map_data_error(
        self,
        error: DataError,
        *,
        id: int | None = None,
    ) -> AppValidationError:
        mysql_code = self._extract_dbapi_code(error)
        detail = self._build_model_detail(id=id)
        return AppValidationError(
            message="数据格式或长度不符合数据库约束",
            detail={**detail, "db_error_code": mysql_code} if mysql_code is not None else detail,
            internal_message=str(error),
        )

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
            stmt = self._apply_default_ordering(
                select(self.model).offset(offset).limit(limit)
            )
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
        except DataError as e:
            raise self._map_data_error(e) from e
        except IntegrityError as e:
            raise self._map_integrity_error(e) from e
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
        通用 update 不允许空更新，也不允许直接改写系统字段。
        """
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return None
        self._validate_update_fields(kwargs)
        try:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            await self.session.flush()
            if refresh:
                await self.session.refresh(obj)
            return obj
        except DataError as e:
            raise self._map_data_error(e, id=id) from e
        except IntegrityError as e:
            raise self._map_integrity_error(e, id=id) from e
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
        except IntegrityError as e:
            raise self._map_integrity_error(e, id=id) from e
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

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        super().__init__(session, model)
        missing_fields = [
            field_name
            for field_name in ("is_deleted", "deleted_at")
            if not hasattr(model, field_name)
        ]
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise TypeError(
                f"{type(self).__name__} requires model {model.__name__} "
                f"to define fields: {joined}"
            )

    def _protected_update_fields(self) -> set[str]:
        return super()._protected_update_fields() | {"is_deleted", "deleted_at"}

    async def get_by_id(
        self,
        id: int,
        *,
        strict: bool = False,
        include_deleted: bool = False,
    ) -> T | None:
        """默认忽略软删除数据；恢复/物理删除场景可显式 include_deleted。"""
        try:
            stmt = select(self.model).where(self.model.id == id)
            if not include_deleted:
                stmt = stmt.where(self.model.is_deleted.is_(False))
            result = await self.session.execute(stmt)
            obj = result.scalar_one_or_none()
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
        """分页查询所有未删除记录。"""
        try:
            stmt = self._apply_default_ordering(
                select(self.model)
                .where(self.model.is_deleted.is_(False))
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
        obj = await self.get_by_id(id, strict=True, include_deleted=True)
        if not getattr(obj, "is_deleted", False):
            raise AppValidationError(
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
        obj = await self.get_by_id(id, strict=strict, include_deleted=True)
        if obj is None:
            return False
        try:
            await self.session.delete(obj)
            await self.session.flush()
            return True
        except IntegrityError as e:
            raise self._map_integrity_error(e, id=id) from e
        except SQLAlchemyError as e:
            raise DatabaseError(
                internal_message=str(e),
                log_extra={"model": self.model.__name__, "id": id},
            ) from e

    async def list_deleted(self, offset: int = 0, limit: int = 100) -> list[T]:
        """查询已软删除的记录。"""
        try:
            stmt = self._apply_default_ordering(
                select(self.model)
                .where(self.model.is_deleted.is_(True))
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
                .where(self.model.is_deleted.is_(False))
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
        product = await repo.update(1, expected_version=3, stock=90)  # 自动检查并递增 version
    """

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        super().__init__(session, model)
        if not hasattr(model, "version"):
            raise TypeError(
                f"{type(self).__name__} requires model {model.__name__} to define field: version"
            )

    def _protected_update_fields(self) -> set[str]:
        return super()._protected_update_fields() | {"version"}

    async def update(
        self,
        id: int,
        *,
        expected_version: int | None = None,
        refresh: bool = True,
        strict: bool = False,
        **kwargs,
    ) -> T | None:
        """乐观锁更新：可显式传入 expected_version，适配跨请求的并发更新。"""
        obj = await self.get_by_id(id, strict=strict)
        if obj is None:
            return None
        current_version = expected_version if expected_version is not None else obj.version
        self._validate_update_fields(kwargs)
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
                        "current_version": getattr(obj, "version", None),
                    },
                )
            # 刷新 ORM 对象以反映数据库中的最新状态
            if refresh:
                await self.session.refresh(obj)
            else:
                for key, value in values.items():
                    setattr(obj, key, value)
            return obj
        except AppError:
            raise
        except DataError as e:
            raise self._map_data_error(e, id=id) from e
        except IntegrityError as e:
            raise self._map_integrity_error(e, id=id) from e
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
            print(f"  get_by_id(已删除) -> {await repo.get_by_id(a1.id)}")
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

            p = await repo.update(p.id, expected_version=p.version, stock=90)
            print(f"  更新: stock={p.stock}, version={p.version}")

    # 模拟乐观锁冲突
    async with factory() as session1, factory() as session2:
        repo1 = VersionedRepository(session1, Product)
        repo2 = VersionedRepository(session2, Product)

        async with session1.begin():
            p1 = await repo1.get_by_id(1)
            version1 = p1.version
            print(f"\n  用户A 读取: version={version1}")

        async with session2.begin():
            p2 = await repo2.get_by_id(1)
            version2 = p2.version
            print(f"  用户B 读取: version={version2}")

        async with session1.begin():
            p1 = await repo1.update(1, expected_version=version1, stock=80)
            print(f"  用户A 更新成功: stock={p1.stock}, version={p1.version}")

        async with session2.begin():
            try:
                await repo2.update(1, expected_version=version2, stock=70)
            except OptimisticLockError as e:
                print(f"  用户B 更新失败: {e}")

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    print("\nRepository 演示完成")


if __name__ == "__main__":
    asyncio.run(_demo())
