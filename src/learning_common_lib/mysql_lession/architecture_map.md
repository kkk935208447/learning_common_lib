# 架构映射（architecture_map）— 异步 ORM 在企业分层架构中的角色

本文档说明 SQLAlchemy 异步 ORM 的各个概念如何映射到真实企业分层架构的各个层。

---

## 企业级分层架构

```text
┌─────────────────────────────────────────────┐
│         客户端 (Client)                      │
├─────────────────────────────────────────────┤
│      API 集成层 (FastAPI + Depends)          │
│  路由函数 / Session 依赖注入 / 请求级生命周期  │
├─────────────────────────────────────────────┤
│       仓储层 (Repository Pattern)            │
│  泛型 CRUD / Unit of Work / 事务边界         │
├─────────────────────────────────────────────┤
│       事务层 (Transaction)                   │
│  commit / rollback / savepoint              │
├─────────────────────────────────────────────┤
│       查询层 (Query)                         │
│  select / insert / update / delete          │
├─────────────────────────────────────────────┤
│       会话层 (AsyncSession)                  │
│  工作单元 / 对象状态管理 / flush             │
├─────────────────────────────────────────────┤
│       模型层 (DeclarativeBase / Mapped)      │
│  表映射 / 关系定义 / 字段类型               │
├─────────────────────────────────────────────┤
│       连接层 (Engine / Pool)                 │
│  连接池 / 驱动适配 / 健康检查               │
├─────────────────────────────────────────────┤
│       基础设施 (MySQL)                       │
│  数据库服务器 / asyncmy 驱动                 │
└─────────────────────────────────────────────┘
```

---

## 知识点 → 架构层 → 教程文件 → 模板

| 架构层 | ORM 职责 | 教程示例 | 企业模板 |
|--------|---------|---------|---------|
| 连接层 | create_async_engine、连接池参数、pool_pre_ping | `01_connection/01, 02` | `db_engine.py` |
| 模型层 | DeclarativeBase、Mapped[T]、Mixin 公共字段 | `02_model_definition/01, 02` | `base_model.py` |
| 会话层 | AsyncSession 状态机、expire_on_commit | `04_session_lifecycle/01, 02` | — |
| 查询层 | select/insert/update/delete、过滤分页聚合 | `03_crud_basics/01, 02`、`06_query_patterns/01, 02, 03` | — |
| 事务层 | commit/rollback、begin_nested savepoint | `07_transactions/01, 02` | — |
| 仓储层 | 泛型 Repository、Unit of Work | `08_repository_pattern/01, 02` | `base_repository.py` |
| API 集成层 | Depends 注入 Session、完整 CRUD API | `10_fastapi_integration/01, 02` | `fastapi_db_middleware.py` |

跨层关注点：关系映射（`05_relationships/`）横跨模型层和查询层；性能优化（`09_performance/`）横跨查询层和连接层。

---

## 每一层的职责与规则

### 连接层（Engine / Pool）（硬规则）

- **全局只创建一个 Engine 实例**，通过模块级变量或依赖注入共享
- 必须配置 `pool_pre_ping=True`，避免使用已断开的连接
- `pool_recycle` 必须小于 MySQL 的 `wait_timeout`（默认 28800 秒），推荐 1800
- 应用关闭时必须调用 `await engine.dispose()` 释放连接池
- 不要在每个函数中创建 Engine，这会导致连接池碎片化

```python
import os

from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    os.environ["DATABASE_URL"],
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True,
    pool_timeout=30,
    echo=False,  # 生产环境关闭 SQL 日志
)
```

### 模型层（DeclarativeBase / Mapped）（硬规则）

- **使用 2.0 风格的 `Mapped[T]` + `mapped_column()`**，不要用旧的 `Column()` 风格
- 公共字段（id、created_at、updated_at）抽取为 Mixin，所有模型继承
- 重要业务模型建议显式声明 `__tablename__`；模板也提供自动生成能力，便于教学和快速原型
- 关系字段必须声明加载策略，不要依赖默认的 lazy loading

```python
from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
        }
    )

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
```

### 会话层（AsyncSession）（硬规则）

- **一个请求一个 Session**，用完即关，不要跨请求复用
- 使用 `async_sessionmaker` 创建工厂，不要每次手动构造 `AsyncSession`
- 设置 `expire_on_commit=False`，避免 commit 后访问属性触发隐式 IO
- Session 是工作单元（Unit of Work），它跟踪对象的变更并在 commit 时批量写入

```python
from sqlalchemy.ext.asyncio import async_sessionmaker

async_session = async_sessionmaker(engine, expire_on_commit=False)

async with async_session() as session:
    # 在这个作用域内使用 session
    ...
# 离开作用域自动关闭
```

### 查询层（Select / Insert / Update / Delete）（硬规则）

- **使用 2.0 风格的 `select()` 函数**，不要用旧的 `session.query()` API
- 所有查询通过 `session.execute()` 执行，结果用 `scalars()` 提取 ORM 对象
- 条件过滤使用 `where()` 而不是 `filter()`（两者等价，但 `where()` 是 2.0 推荐风格）
- 关联查询必须显式指定加载策略（`selectinload` / `joinedload`）

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

stmt = (
    select(User)
    .where(User.is_active == True)
    .options(selectinload(User.posts))
    .order_by(User.created_at.desc())
)
result = await session.execute(stmt)
users = result.scalars().all()
```

### 事务层（commit / rollback / savepoint）（硬规则）

- **最小事务范围** — 事务只包裹必须原子执行的操作，不要把整个请求包在一个大事务里
- 使用 `async with session.begin()` 自动管理 commit/rollback
- 需要部分回滚时使用 `session.begin_nested()` 创建 savepoint
- 不要在事务中做耗时的非数据库操作（HTTP 调用、文件 IO），这会长时间占用连接

```python
async with session.begin():
    session.add(order)
    # 尝试扣减库存，失败则部分回滚
    async with session.begin_nested():
        try:
            await deduct_inventory(session, item_id, quantity)
        except InsufficientInventoryError:
            pass  # savepoint 自动回滚，order 仍然会被提交
```

### 仓储层（Repository Pattern）（硬规则）

- **Repository 只负责数据访问**，不包含业务逻辑
- 使用泛型基类 `BaseRepository[T]` 封装通用 CRUD，具体 Repository 继承并扩展
- Repository 接收 Session 作为构造参数，不自己创建 Session
- Unit of Work 协调多个 Repository 的事务边界

```python
from typing import TypeVar, Generic

T = TypeVar("T")

class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: int) -> T | None:
        return await self.session.get(self.model, id)
```

### API 集成层（FastAPI + Depends）（硬规则）

- **Session 通过 `Depends` 注入**，不要在路由函数中手动创建
- 使用 `async generator` 依赖实现请求级 Session 生命周期
- 路由函数只负责参数解析和调用 Service/Repository，不直接操作 Session
- 应用启动时创建 Engine，关闭时 dispose

```python
from fastapi import Depends

async def get_session():
    async with async_session() as session:
        yield session

@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404)
    return user
```

---

## 数据流：一个请求的完整生命周期

```text
客户端请求 GET /users/1
  │
  ▼
FastAPI 路由匹配 → Depends(get_session) 触发
  │
  ▼
连接层：从连接池获取连接 → 创建 AsyncSession
  │
  ▼
仓储层：UserRepository.get_by_id(1)
  │
  ▼
查询层：select(User).where(User.id == 1)
  │
  ▼
会话层：session.execute(stmt) → 发送 SQL 到 MySQL
  │
  ▼
模型层：将数据库行映射为 User ORM 对象
  │
  ▼
路由函数：返回 User 数据
  │
  ▼
Session 关闭 → 连接归还连接池
  │
  ▼
客户端收到 JSON 响应
```

---

## 从教程到生产的演进路径

1. 先用示例理解每个层的概念和 API（01-07 章）
2. 用第 08 章理解如何将数据访问封装为 Repository 模式
3. 用第 09 章理解性能优化的关键手段
4. 用第 10 章理解如何在 FastAPI 中串联所有层
5. 阅读 `templates/` 了解如何将架构封装为可复用组件
6. 在实际项目中按架构层组合模板，根据业务需求扩展：添加读写分离、多数据库支持、查询缓存等
