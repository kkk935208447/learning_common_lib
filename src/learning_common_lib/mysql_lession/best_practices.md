# 异步 ORM 最佳实践

这份文档只讲"推荐做法"。反模式和常见错误见 [pitfalls.md](pitfalls.md)。

---

## 1. 引擎配置：生产级连接池参数

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "mysql+asyncmy://root:123456@localhost:3306/tutorial_db",
    pool_size=10,          # 连接池常驻连接数
    max_overflow=20,       # 超出 pool_size 后允许的临时连接数
    pool_recycle=1800,     # 连接最大存活秒数，必须 < MySQL wait_timeout
    pool_pre_ping=True,    # 每次取连接前发送 ping，剔除已断开的连接
    pool_timeout=30,       # 等待可用连接的超时秒数
    echo=False,            # 生产环境关闭 SQL 日志
)
```

关键参数说明：

| 参数 | 推荐值 | 为什么 |
|------|--------|--------|
| `pool_size` | 5-20 | 根据并发量调整，太小会排队，太大浪费 MySQL 连接数 |
| `max_overflow` | pool_size 的 1-2 倍 | 应对突发流量，超出后新请求等待 |
| `pool_recycle` | 1800 | MySQL 默认 wait_timeout=28800，recycle 必须更小 |
| `pool_pre_ping` | True | 避免拿到已被 MySQL 关闭的连接，几乎无性能开销 |
| `echo` | False | 生产环境不要开，SQL 日志量巨大，用 logging 按需开启 |

---

## 2. Session 管理：一个请求一个 Session

```python
from sqlalchemy.ext.asyncio import async_sessionmaker

async_session = async_sessionmaker(engine, expire_on_commit=False)

# 正确 — 请求级 Session
async with async_session() as session:
    user = await session.get(User, user_id)
    # session 在 with 块结束时自动关闭

# 错误 — 全局共享 Session
global_session = async_session()  # 多个请求共享，状态混乱
```

`expire_on_commit=False` 是异步场景的必选项。默认行为是 commit 后标记所有属性为过期，下次访问时触发隐式 SQL 查询 — 在异步环境中这会抛出 `MissingGreenlet` 错误。

---

## 3. 模型定义：2.0 风格 + 公共字段抽取

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, func
from datetime import datetime

class Base(DeclarativeBase):
    pass

class IdMixin:
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
```

要点：

- 使用 `Mapped[T]` 声明字段类型，IDE 能正确推断类型
- `mapped_column()` 替代旧的 `Column()`，参数完全兼容
- 公共字段抽取为 Mixin，避免每个模型重复定义 id/created_at/updated_at
- `server_default=func.now()` 让数据库生成时间戳，比 Python 端 `default=datetime.utcnow` 更可靠

---

## 4. 查询：始终使用 2.0 风格 select()

```python
from sqlalchemy import select

# 正确 — 2.0 风格
stmt = select(User).where(User.email == "test@example.com")
result = await session.execute(stmt)
user = result.scalars().first()

# 不推荐 — 1.x 旧风格（在异步中不可用）
# user = session.query(User).filter_by(email="test@example.com").first()
```

2.0 风格的优势：

- `select()` 返回的是可组合的 SQL 表达式，可以在不同函数间传递和修改
- `session.execute()` 是统一的执行入口，ORM 查询和 Core 查询用同一个 API
- 异步环境中 `session.query()` 完全不可用，只有 `select()` 风格支持 async

---

## 5. 关系加载：显式指定，禁用 lazy loading

```python
from sqlalchemy.orm import selectinload, joinedload

# 正确 — 显式预加载
stmt = select(User).options(selectinload(User.posts))
result = await session.execute(stmt)
users = result.scalars().all()
for user in users:
    print(user.posts)  # 已加载，不会触发额外查询

# 错误 — 依赖 lazy loading（异步中直接报错）
stmt = select(User)
result = await session.execute(stmt)
users = result.scalars().all()
for user in users:
    print(user.posts)  # MissingGreenlet 错误！
```

加载策略选择：

| 策略 | 适用场景 | SQL 行为 |
|------|---------|---------|
| `selectinload` | 一对多关系、集合属性 | 额外一条 SELECT ... WHERE id IN (...) |
| `joinedload` | 多对一关系、单个对象属性 | LEFT JOIN 合并到主查询 |
| `subqueryload` | 大数据量一对多 | 额外一条子查询 |

经验法则：**一对多用 `selectinload`，多对一用 `joinedload`**。`selectinload` 不会产生笛卡尔积，是最安全的默认选择。

---

## 6. 事务：最小事务范围 + savepoint 部分回滚

```python
# 正确 — 最小事务范围
async with session.begin():
    session.add(order)
    await session.flush()  # 获取 order.id

# 正确 — savepoint 部分回滚
async with session.begin():
    session.add(order)
    try:
        async with session.begin_nested():
            await deduct_inventory(session, item_id, qty)
    except InsufficientInventoryError:
        # savepoint 回滚，但 order 仍然会被提交
        order.status = "pending_inventory"

# 错误 — 事务中做 HTTP 调用
async with session.begin():
    session.add(order)
    await notify_external_service(order)  # 耗时操作，长时间占用连接！
    session.add(log_entry)
```

原则：

- 事务只包裹数据库操作，不包裹 HTTP 调用、文件 IO 等耗时操作
- 需要部分回滚时用 `begin_nested()` 创建 savepoint
- `session.begin()` 上下文管理器会在正常退出时 commit，异常时 rollback

---

## 7. Repository 模式：泛型基类 + 依赖注入

```python
from typing import TypeVar, Generic, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: int) -> T | None:
        return await self.session.get(self.model, id)

    async def list_all(self, offset: int = 0, limit: int = 100) -> Sequence[T]:
        stmt = select(self.model).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)

class UserRepository(BaseRepository["User"]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> "User | None":
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalars().first()
```

要点：

- Repository 接收 Session，不自己创建 — 事务边界由调用方控制
- 泛型基类封装通用 CRUD，具体 Repository 只添加领域特定的查询方法
- `flush()` 而不是 `commit()` — 让调用方决定何时提交事务

---

## 7.1 refresh 策略：按需刷新，避免多余往返

`flush()` 后调用 `refresh(obj)` 会额外发一条 `SELECT` 从数据库重新加载对象的所有字段。这在以下场景有用：

- 需要读取 `server_default` 生成的字段（如 `created_at`、自增 `id`）
- 需要读取数据库触发器修改的字段

但在高 QPS 场景下，每次 create/update 都 refresh 意味着多一次数据库往返。优化策略：

```python
# 方式 1：flush 后只取 id，不 refresh 全部字段
self.session.add(obj)
await self.session.flush()
# obj.id 已可用（flush 后 autoincrement 字段会被填充）
return obj  # 不调用 refresh，省一次 SELECT

# 方式 2：需要完整字段时才 refresh
await self.session.refresh(obj)  # 多一次 SELECT，但拿到所有 server_default 字段
```

经验法则：教程和内部工具可以无脑 refresh（简单直观）；面向用户的高并发 API 应按需决定。

---

## 8. 连接池调优：监控与诊断

```python
from sqlalchemy import event

# 监控连接池状态
@event.listens_for(engine.sync_engine, "checkout")
def on_checkout(dbapi_conn, connection_record, connection_proxy):
    """连接从池中取出时触发"""
    pass

@event.listens_for(engine.sync_engine, "checkin")
def on_checkin(dbapi_conn, connection_record):
    """连接归还池中时触发"""
    pass

# 运行时查看连接池状态
pool = engine.pool
print(f"池大小: {pool.size()}")
print(f"已检出: {pool.checkedout()}")
print(f"溢出: {pool.overflow()}")
```

调优建议：

| 指标 | 健康范围 | 异常信号 |
|------|---------|---------|
| checkedout / pool_size | < 80% | 持续 > 90% 说明连接不够或有泄漏 |
| overflow | 偶尔 > 0 | 持续 > 0 说明 pool_size 太小 |
| 等待超时 | 无 | 出现 `TimeoutError` 说明连接池耗尽 |

生产环境建议将连接池指标接入 Prometheus / Datadog 监控。

---

## 9. 生产级代码自查清单

提交数据访问层代码前，确认：

- [ ] Engine 全局只创建一个，应用关闭时调用 `await engine.dispose()`
- [ ] `pool_pre_ping=True` 已开启
- [ ] `pool_recycle` 小于 MySQL `wait_timeout`
- [ ] `expire_on_commit=False` 已设置
- [ ] 所有关系加载都显式指定了 `selectinload` / `joinedload`
- [ ] 没有在异步代码中使用 `session.query()` 旧 API
- [ ] Session 在请求结束时正确关闭（使用 `async with` 或 `Depends`）
- [ ] 事务范围最小化，不包含非数据库的耗时操作
- [ ] Repository 不自己创建 Session，通过构造参数接收
- [ ] 批量操作使用 `insert().values()` 而不是循环 `session.add()`
