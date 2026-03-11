# 学习路线（roadmap）

## 版本要求

- Python 3.11+
- MySQL 8.0+
- SQLAlchemy 2.0+（使用 2.0 风格的 `Mapped` 类型注解和 `select()` 查询语法）
- asyncmy（纯 Python 异步 MySQL 驱动）
- 当前仓库 uv 环境约束为 `>=3.11,<3.12`，示例语义上兼容更高版本但未验证
- 第 10 章需要安装 FastAPI 和 uvicorn：`uv add fastapi uvicorn`
- 安装数据库依赖：`uv add sqlalchemy asyncmy`

## 学习顺序与理由

### 第一阶段：连接与引擎（01_connection/）

一切从连接开始。不理解 Engine 和连接池，后面的 Session、事务、性能优化都是空中楼阁。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 1 | `01_async_engine_basic.py` | create_async_engine 参数、连接池配置、pool_pre_ping | 最小可运行单元 |
| 2 | `02_connection_pool.py` | 连接池状态观察、并发获取连接、pool_size/max_overflow | Engine 之上的第一层抽象 |

### 第二阶段：模型定义（02_model_definition/）

有了连接，下一步是定义数据模型。模型是 ORM 的核心，所有 CRUD 操作都围绕模型展开。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 3 | `01_declarative_base.py` | DeclarativeBase、Mapped[T]、mapped_column 2.0 风格 | ORM 模型的基础 |
| 4 | `02_mapped_column_types.py` | 常见列类型、nullable/default/server_default、字段约束 | 企业级模型的标准做法 |

### 第三阶段：CRUD 基础（03_crud_basics/）

模型定义好了，开始做最基本的增删改查。这是日常开发中最高频的操作。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 5 | `01_insert_and_add.py` | session.add / add_all / flush / commit 基本用法 | CRUD 的最小闭环 |
| 6 | `02_select_update_delete.py` | select() / update / delete 的 2.0 风格写法 | CRUD 完整覆盖 |

### 第四阶段：Session 生命周期（04_session_lifecycle/）

CRUD 能跑了，但 Session 的状态管理是异步 ORM 最容易踩坑的地方。不理解 Session 状态机，后面遇到 detached instance 错误会一头雾水。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 7 | `01_session_scope.py` | Session 作用域、手动 commit 与 `session.begin()` 对比 | 理解 Session 生命周期 |
| 8 | `02_session_states.py` | transient/pending/persistent/detached/deleted、expire_on_commit | 异步场景最常见的坑 |

### 第五阶段：关系映射（05_relationships/）

单表 CRUD 掌握后，进入多表关联。关系映射是 ORM 区别于原始 SQL 的核心价值。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 9 | `01_one_to_many.py` | relationship、ForeignKey、back_populates | 最常见的关系类型 |
| 10 | `02_many_to_many.py` | 关联表、secondary 参数、多对多配置 | 关系映射完整覆盖 |

### 第六阶段：查询模式（06_query_patterns/）

关系建好了，查询需求会变得复杂。这一阶段覆盖生产中最常用的查询模式。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 11 | `01_filter_and_where.py` | where / and_ / or_ / in_ 等条件组合 | 查询的基本功 |
| 12 | `02_join_and_subquery.py` | join / subquery / exists 风格查询 | 多表查询的基础 |
| 13 | `03_pagination_and_ordering.py` | offset/limit 与 cursor 分页、order_by 排序 | 列表接口必备 |

### 第七阶段：事务管理（07_transactions/）

查询是读，事务是写的保障。理解事务边界和 savepoint 是写出数据一致性代码的关键。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 14 | `01_commit_rollback.py` | 手动 commit/rollback、begin() 上下文管理器 | 事务的基本操作 |
| 15 | `02_nested_savepoint.py` | begin_nested() savepoint、部分回滚 | 复杂业务的事务策略 |

### 第八阶段：Repository 模式（08_repository_pattern/）

有了前面的基础，开始封装数据访问层。Repository 模式是企业级项目的标准架构。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 16 | `01_generic_repository.py` | 泛型 BaseRepository[T]、通用 CRUD 方法 | 消除重复代码 |
| 17 | `02_unit_of_work.py` | Unit of Work 模式、多 Repository 协调 | 事务边界管理 |

### 第九阶段：性能优化（09_performance/）

功能正确之后，关注性能。N+1 查询和批量操作是 ORM 性能的两大核心问题。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 18 | `01_eager_loading.py` | selectinload / joinedload 对比 | 解决 N+1 查询 |
| 19 | `02_bulk_operations.py` | session.add / add_all / insert().values() 批量写入 | 大数据量写入优化 |

### 第十阶段：FastAPI 集成（10_fastapi_integration/）— 终极章节

放在最后，因为它综合了前面所有知识：连接管理、Session 生命周期、Repository、事务，全部在 FastAPI 的请求生命周期中串联起来。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 20 | `01_lifespan_and_session.py` | lifespan 管理 Engine、Depends 注入 AsyncSession | FastAPI + ORM 的桥梁 |
| 21 | `02_full_crud_api.py` | 完整 CRUD API、Repository + Router 配合、统一响应格式 | 综合运用所有知识 |

## 学完示例后

阅读 `templates/` 目录，了解如何将这些知识点封装为企业级可复用组件。

阅读顺序建议：`db_engine.py` → `db_session.py` → `base_model.py` → `base_repository.py` → `fastapi_db_middleware.py`
