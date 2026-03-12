# SQLAlchemy 异步 ORM 企业级模板包

这是一套企业级 SQLAlchemy 异步 ORM 模板包，提供从数据库引擎创建到 FastAPI 集成的完整解决方案，包含异常体系、软删除、乐观锁等企业级模式。

## 使用方式

将 `templates/` 目录复制到你的项目中，通过环境变量 `DATABASE_URL` 配置数据库连接。表结构变更请使用 Alembic 迁移，模板默认不会在启动时自动建表。

## 分层设计

模板分为 core 层和集成层，便于理解复用边界：

- **core 层**（无 FastAPI/Pydantic 依赖）：`error_registry`, `error_base`, `mixins`, `base_model`, `base_repository`, `db_engine`, `db_session`
- **集成层**（需要 FastAPI/Pydantic）：`error_handler`, `fastapi_db_middleware`

当前实现已把 FastAPI 集成符号做成可选导入；如果环境里没有安装 FastAPI/Pydantic，core 层仍可正常使用。
如果你在非 FastAPI 项目里想最小化依赖，仍然推荐优先从具体子模块导入，例如 `templates.base_repository`、`templates.base_model`。

FastAPI 集成层推荐显式导入：

```python
# core 层 — 任何项目都能用
from templates import BaseRepository, NotFoundError, SoftDeleteMixin

# 集成层 — 仅 FastAPI 项目需要
from templates.error_handler import register_exception_handlers, RequestIdMiddleware, ErrorResponse
from templates.fastapi_db_middleware import db_lifespan, get_db_session
```

## 当前边界

- `db_engine.py` 里的单例 helper 更适合简单应用或教程演示；复杂项目通常会把 Engine 生命周期放到应用装配层
- `BaseRepository` 适合标准 CRUD；复杂检索、聚合统计、读写分离仍应由具体 Repository 或 Query Service 扩展
- `base_model.py` 目前没有强制统一时区策略；生产项目应明确选择 UTC 存储策略并在全团队统一

## 模块说明

| 文件 | 说明 |
|------|------|
| `__init__.py` | 公开 API 导出，分 core 层和集成层，附 `__all__` 列表 |
| `db_engine.py` | 引擎创建与连接池配置，支持单例模式和环境变量读取 |
| `db_session.py` | 异步 Session 工厂与生命周期管理（open/close），事务由调用方控制 |
| `base_model.py` | 声明式基类与公共字段混入（id、created_at、updated_at） |
| `mixins.py` | 可选混入：SoftDeleteMixin（软删除）、VersionMixin（乐观锁） |
| `error_registry.py` | 错误码注册表，(code, message, http_status) 三元组 + 导入时唯一性校验 |
| `error_base.py` | 异常层级树，AppError → ClientError/ServerError → 具体异常类 |
| `error_handler.py` | FastAPI 全局异常处理器 + RequestIdMiddleware + ErrorResponse 统一响应 |
| `base_repository.py` | 泛型 CRUD 仓储 + 异常转换 + SoftDeleteRepository + VersionedRepository |
| `fastapi_db_middleware.py` | FastAPI 生命周期管理 + `app.state` 挂载 Engine/SessionFactory + Session 依赖注入 |

## 依赖关系

```
db_engine ← db_session
base_model ← mixins
base_model ← base_repository
error_registry ← error_base ← error_handler
error_base ← base_repository (异常转换)
mixins ← base_repository (SoftDeleteRepository / VersionedRepository)
fastapi_db_middleware ← (db_engine, db_session, base_model, error_handler)
```

箭头表示"被依赖"：`A ← B` 意味着 B 导入了 A。

完整依赖图：

```
                    ┌──────────────┐
                    │  db_engine   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  db_session  │
                    └──────┬───────┘
                           │
┌──────────────┐    ┌──────▼───────────────┐    ┌────────────────┐
│  base_model  │◄───│ fastapi_db_middleware │───►│ error_handler  │
└──┬───────┬───┘    └──────────────────────┘    └───────▲────────┘
   │       │                                            │
   ▼       ▼                                    ┌───────┴────────┐
┌──────┐ ┌─────────────────┐                    │   error_base   │
│mixins│ │ base_repository │───────────────────►└───────▲────────┘
└──┬───┘ └────────┬────────┘                            │
   │              │                             ┌───────┴────────┐
   └──────────────┘                             │ error_registry │
  (SoftDelete/Versioned                         └────────────────┘
   Repository 依赖 mixins)
```

## Repository 继承链选择指南

```
BaseRepository          — 基础 CRUD + 异常转换（适合大多数场景）
  └── SoftDeleteRepository  — + 软删除/恢复/已删除列表（需要审计轨迹时使用）
        └── VersionedRepository — + 乐观锁（需要防止并发覆盖时使用）
```

- 不需要软删除和乐观锁 → `BaseRepository`
- 需要软删除但不需要乐观锁 → `SoftDeleteRepository`
- 需要全套企业级特性 → `VersionedRepository`

## 快速上手

### 最小 CRUD

```python
from templates import BaseRepository, Base, TimestampMixin

class User(TimestampMixin, Base):
    name: Mapped[str] = mapped_column(String(50))

repo = BaseRepository(session, User)
user = await repo.create(User(name="张三"))
user = await repo.get_by_id(1, strict=True)  # 不存在抛 NotFoundError
```

### 异常处理

```python
from templates import NotFoundError, DuplicateError

try:
    await repo.create(User(name="张三", email="duplicate@example.com"))
except DuplicateError as e:
    print(f"唯一约束冲突: {e.code} - {e.message}")
```

### 软删除

```python
from templates import SoftDeleteRepository, SoftDeleteMixin

class Article(SoftDeleteMixin, TimestampMixin, Base):
    title: Mapped[str] = mapped_column(String(200))

repo = SoftDeleteRepository(session, Article)
await repo.delete(1)          # 软删除
await repo.get_by_id(1)       # None（默认不返回已删除记录）
await repo.restore(1)         # 恢复
await repo.hard_delete(1)     # 物理删除
```

### 乐观锁

```python
from templates import VersionedRepository, VersionMixin, SoftDeleteMixin, OptimisticLockError

class Product(VersionMixin, SoftDeleteMixin, TimestampMixin, Base):
    stock: Mapped[int] = mapped_column(Integer, default=0)

repo = VersionedRepository(session, Product)
try:
    product = await repo.get_by_id(1, strict=True)
    await repo.update(1, expected_version=product.version, stock=90)
except OptimisticLockError:
    # 重新读取最新版本后重试
    pass
```

## 推荐阅读顺序

1. `db_engine.py` — 引擎和连接池
2. `db_session.py` — Session 生命周期
3. `base_model.py` — 模型基类和公共字段
4. `error_registry.py` → `error_base.py` — 错误码和异常层级
5. `mixins.py` — 软删除和乐观锁混入
6. `base_repository.py` — 仓储模式（基础 → 软删除 → 乐观锁）
7. `error_handler.py` — 全局异常处理器
8. `fastapi_db_middleware.py` — FastAPI 集成

## 生产环境 checklist

- [ ] `DATABASE_URL` 通过环境变量配置，不硬编码
- [ ] `pool_pre_ping=True` 已开启
- [ ] `pool_recycle` 小于 MySQL `wait_timeout`
- [ ] `expire_on_commit=False` 已设置
- [ ] 全局异常处理器已注册（`register_exception_handlers`）
- [ ] RequestIdMiddleware 已添加（链路追踪）
- [ ] Repository 层异常已转换（不泄漏 SQLAlchemy 异常给客户端）
- [ ] `IntegrityError` 已按错误码细分，不把所有约束错误都误判为重复数据
- [ ] 软删除数据有定期归档策略
- [ ] 乐观锁更新明确携带 `expected_version`，并配套重试机制
- [ ] 表结构变更使用 Alembic 迁移
