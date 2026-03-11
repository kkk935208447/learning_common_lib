# 异步 ORM 常见坑与反模式

这份文档只讲"什么会出错、为什么出错"。推荐做法见 [best_practices.md](best_practices.md)。

---

## 1. 异步中使用 lazy loading 导致 MissingGreenlet 错误

```python
stmt = select(User)
result = await session.execute(stmt)
users = result.scalars().all()

for user in users:
    print(user.posts)  # MissingGreenlet: greenlet_spawn has not been called
```

原因：SQLAlchemy 的 lazy loading 需要同步发起 SQL 查询，但异步环境中没有同步 IO 通道。访问未加载的关系属性时，SQLAlchemy 尝试隐式发起查询，发现当前不在 greenlet 上下文中，直接报错。

这是异步 ORM 最常见的错误，没有之一。

正确做法：

```python
stmt = select(User).options(selectinload(User.posts))
result = await session.execute(stmt)
users = result.scalars().all()

for user in users:
    print(user.posts)  # 已预加载，正常访问
```

---

## 2. 忘记 await session 操作

```python
# 错误 — 忘记 await
session.execute(stmt)       # 返回 coroutine，SQL 根本没执行
session.commit()            # 返回 coroutine，事务没提交
session.refresh(user)       # 返回 coroutine，对象没刷新

# 正确
await session.execute(stmt)
await session.commit()
await session.refresh(user)
```

后果：程序不报错（Python 只会发出 RuntimeWarning），但数据库操作完全没有执行。数据"莫名其妙"没写入，查询"莫名其妙"返回 None。

排查技巧：如果看到 `RuntimeWarning: coroutine 'xxx' was never awaited`，说明漏了 await。

---

## 3. expire_on_commit=True 导致 detached instance 错误

```python
# 默认 expire_on_commit=True
async_session = async_sessionmaker(engine)  # 没设置 expire_on_commit=False

async with async_session() as session:
    user = User(name="test", email="test@example.com")
    session.add(user)
    await session.commit()
    print(user.name)  # sqlalchemy.orm.exc.DetachedInstanceError!
```

原因：`expire_on_commit=True`（默认值）会在 commit 后将所有已加载属性标记为过期。下次访问属性时 SQLAlchemy 尝试重新从数据库加载，但此时 Session 可能已关闭或不在有效状态，导致 DetachedInstanceError 或 MissingGreenlet。

正确做法：

```python
async_session = async_sessionmaker(engine, expire_on_commit=False)
```

---

## 4. 连接池耗尽（pool_size 太小 / 忘记关闭 Session）

```python
# 场景一：pool_size 太小
engine = create_async_engine(url, pool_size=2, max_overflow=0)
# 3 个并发请求同时到达 → 第 3 个请求等待超时 → TimeoutError

# 场景二：Session 没有正确关闭
async def bad_handler():
    session = async_session()
    result = await session.execute(select(User))
    return result.scalars().all()
    # session 没有关闭！连接永远不会归还连接池

# 场景三：异常导致 Session 没关闭
async def also_bad():
    session = async_session()
    await session.execute(select(User))
    raise ValueError("业务错误")  # session.close() 永远不会被调用
```

后果：连接池中的连接被逐渐耗尽，新请求全部超时。在高并发场景下，几分钟内就能把连接池打满。

正确做法：

```python
# 始终使用 async with 确保 Session 关闭
async with async_session() as session:
    result = await session.execute(select(User))
    return result.scalars().all()
# 无论正常退出还是异常，Session 都会被关闭，连接归还连接池
```

---

## 5. N+1 查询问题

```python
# 假设有 100 个用户，每个用户有多篇文章
stmt = select(User)
result = await session.execute(stmt)
users = result.scalars().all()  # 1 条 SQL

for user in users:
    # 如果用了 run_sync 或同步 Session，每次访问 posts 触发 1 条 SQL
    # 总共 1 + 100 = 101 条 SQL！
    print(len(user.posts))
```

在异步环境中，这个问题通常表现为 MissingGreenlet 错误（见第 1 条）。但如果你用 `session.run_sync()` 绕过了异步限制，N+1 问题会静默发生，严重拖慢性能。

正确做法：

```python
stmt = select(User).options(selectinload(User.posts))
result = await session.execute(stmt)
users = result.scalars().all()  # 2 条 SQL：1 条查用户，1 条查所有相关文章

for user in users:
    print(len(user.posts))  # 直接从内存读取，无额外查询
```

---

## 6. 事务中混用 session.execute 和 session.add 的时序问题

```python
async with session.begin():
    user = User(name="test", email="test@example.com")
    session.add(user)

    # 此时 user.id 是 None！因为还没有 flush 到数据库
    order = Order(user_id=user.id)  # user_id=None，外键约束失败！
    session.add(order)
```

原因：`session.add()` 只是把对象放入 Session 的待写入队列，并不立即执行 INSERT。`user.id` 要等到 `flush()` 或 `commit()` 后才会被数据库赋值。

正确做法：

```python
async with session.begin():
    user = User(name="test", email="test@example.com")
    session.add(user)
    await session.flush()  # 立即执行 INSERT，user.id 现在有值了

    order = Order(user_id=user.id)  # 正确
    session.add(order)
```

或者使用 relationship 让 SQLAlchemy 自动处理外键：

```python
async with session.begin():
    user = User(name="test", email="test@example.com")
    order = Order()
    user.orders.append(order)  # 通过关系关联，SQLAlchemy 自动处理外键
    session.add(user)
```

---

## 7. 忘记 dispose engine

```python
# 应用启动
engine = create_async_engine(url)

# 应用运行...

# 应用关闭 — 忘记 dispose
# 连接池中的连接不会被正确关闭
# MySQL 端看到大量 Sleep 状态的连接
```

后果：

- MySQL 连接数持续增长，最终达到 `max_connections` 上限
- 频繁重启应用时尤其明显，每次重启都泄漏一批连接
- MySQL 端 `SHOW PROCESSLIST` 看到大量 Sleep 状态的连接

正确做法：

```python
# FastAPI lifespan
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # 启动时：Engine 已在模块级创建
    yield
    # 关闭时：释放连接池
    await engine.dispose()

app = FastAPI(lifespan=lifespan)
```

---

## 8. 在 async 中使用同步 API

```python
# 错误 — 在异步函数中使用同步 Engine
from sqlalchemy import create_engine

sync_engine = create_engine("mysql+pymysql://root:123456@localhost:3306/tutorial_db")

async def get_user(user_id: int):
    with Session(sync_engine) as session:
        # 这会阻塞整个事件循环！
        # 其他所有协程都被卡住，直到这条 SQL 执行完毕
        return session.get(User, user_id)
```

后果：同步数据库操作会阻塞事件循环。如果 SQL 执行需要 100ms，这 100ms 内整个应用的所有请求都被卡住。在高并发场景下，响应时间会急剧恶化。

正确做法：

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

engine = create_async_engine("mysql+asyncmy://root:123456@localhost:3306/tutorial_db")
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_user(user_id: int):
    async with async_session() as session:
        return await session.get(User, user_id)
```

如果必须使用同步库（比如某些不支持异步的 ORM 插件），用 `run_in_executor` 把同步操作放到线程池：

```python
import asyncio

async def get_user_sync_fallback(user_id: int):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_get_user, user_id)
```

---

## 一句话总结

异步 ORM 真正难的地方不是 SQL 怎么写，而是生命周期管理：连接什么时候创建和释放、Session 什么时候打开和关闭、对象什么时候过期和刷新、事务什么时候提交和回滚。把这四个生命周期理清楚，90% 的坑都能避开。
