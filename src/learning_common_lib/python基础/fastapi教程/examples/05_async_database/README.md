# 05_async_database

这一章演示 FastAPI 中最常见的异步数据库开发方式：

1. `AsyncSession + ORM CRUD`
2. `Repository 模式 + Depends`

和前面的版本相比，这一章现在不再使用 `:memory:` 内存数据库，而是改成了**文件型 SQLite**：

- `01_async_sqlalchemy_crud.db`
- `02_repository_pattern.db`

这样做的好处是更接近真实项目：

- 数据库不是“请求一停就没了”
- 服务重启后，数据仍然存在
- 测试可以验证“持久化”这件事，而不仅仅是“同一个进程里还能读到数据”

## 你会看到的几个关键函数

- `create_app()`
  创建带 `lifespan` 的 FastAPI 应用
- `lifespan()`
  启动时建表，关闭时释放数据库连接
- `init_database()`
  启动服务前建表
- `reset_database()`
  测试前清空数据库并重新建表
- `dispose_database()`
  服务退出时关闭数据库连接
- `get_database_file()`
  返回当前示例使用的 `.db` 文件路径

## 为什么这里仍然使用 SQLite

这章的重点是“异步数据库访问模式”，不是数据库运维。

教学场景下：

- 用 SQLite 文件最轻量
- 不需要额外安装 PostgreSQL
- 但又能模拟“真正的数据库文件持久化”

生产提醒：

- 生产环境更常见的是 PostgreSQL + `asyncpg`
- SQLite 更适合本地开发、教程、轻量工具或嵌入式场景
- 这章的代码结构可以直接迁移到 PostgreSQL，主要只需要替换连接 URL
- 用 `lifespan` 管理数据库初始化与关闭，比在 `__main__` 里手动拼 `asyncio.run(...)` 更符合 FastAPI 项目风格
