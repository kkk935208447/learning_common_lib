# SQLAlchemy 异步 ORM 教程（偏生产级）

这份教程与当前项目代码独立，目标是提供一套可直接运行、可逐步学习、并适合企业级项目参考的 SQLAlchemy 异步 ORM 学习资料。

适用对象：

- 想系统掌握 SQLAlchemy 2.0 异步 ORM 的开发者
- 在 FastAPI 项目中遇到数据库连接管理混乱、Session 生命周期不清晰的工程师
- 想建立企业级 Repository 模式和数据访问层架构的同学

---

## 环境要求

- Python 3.11+
- MySQL 8.0+
- asyncmy（异步 MySQL 驱动）
- SQLAlchemy 2.0+（使用 2.0 风格的 Mapped 类型注解和 select() 查询语法）
- 第 10 章 FastAPI 集成需要安装 FastAPI 和 uvicorn：`uv add fastapi uvicorn`
- 安装数据库依赖：`uv add sqlalchemy asyncmy`

---

## 数据库准备

在 MySQL 中创建教程数据库：

```sql
CREATE DATABASE IF NOT EXISTS tutorial_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

教程中使用的连接字符串：

```
mysql+asyncmy://root:123456@localhost:3306/tutorial_db
```

---

## 目录结构

```text
mysql_lession/
├── readme.md                 ← 你在这里
├── roadmap.md                ← 学习路线与排序理由
├── architecture_map.md       ← 异步 ORM → 企业架构层映射
├── best_practices.md         ← 推荐做法
├── pitfalls.md               ← 反模式与常见坑
├── smoke/
│   └── run_all_examples.py   ← 自动运行所有示例的 smoke 测试
├── examples/
│   ├── 01_connection/
│   │   ├── 01_async_engine_basic.py
│   │   └── 02_connection_pool.py
│   ├── 02_model_definition/
│   │   ├── 01_declarative_base.py
│   │   └── 02_mapped_column_types.py
│   ├── 03_crud_basics/
│   │   ├── 01_insert_and_add.py
│   │   └── 02_select_update_delete.py
│   ├── 04_session_lifecycle/
│   │   ├── 01_session_scope.py
│   │   └── 02_session_states.py
│   ├── 05_relationships/
│   │   ├── 01_one_to_many.py
│   │   ├── 02_many_to_many.py
│   │   └── 03_missing_greenlet_lazy_loading.py
│   ├── 06_query_patterns/
│   │   ├── 01_filter_and_where.py
│   │   ├── 02_join_and_subquery.py
│   │   └── 03_pagination_and_ordering.py
│   ├── 07_transactions/
│   │   ├── 01_commit_rollback.py
│   │   └── 02_nested_savepoint.py
│   ├── 08_repository_pattern/
│   │   ├── 01_generic_repository.py
│   │   ├── 02_unit_of_work.py
│   │   ├── 03_soft_delete.py
│   │   └── 04_optimistic_lock.py
│   ├── 09_performance/
│   │   ├── 01_eager_loading.py
│   │   └── 02_bulk_operations.py
│   └── 10_fastapi_integration/
│       ├── 01_lifespan_and_session.py
│       └── 02_full_crud_api.py
└── templates/
    ├── __init__.py               ← 公开 API 导出
    ├── README.md                 ← 模板使用说明
    ├── db_engine.py              ← 引擎创建与连接池配置
    ├── db_session.py             ← 异步 Session 工厂
    ├── base_model.py             ← 声明式基类与公共字段混入
    ├── mixins.py                 ← 软删除 / 乐观锁混入
    ├── error_registry.py         ← 错误码注册表
    ├── error_base.py             ← 异常层级树
    ├── error_handler.py          ← FastAPI 全局异常处理器
    ├── base_repository.py        ← 泛型 CRUD 仓储
    └── fastapi_db_middleware.py   ← FastAPI 生命周期 + Session 注入
```

---

## 如何运行示例

先进入教程目录：

```bash
cd src/learning_common_lib/mysql_lession
```

然后运行任意示例：

```bash
uv run python examples/01_connection/01_async_engine_basic.py
```

或者从仓库根目录直接运行：

```bash
uv run python src/learning_common_lib/mysql_lession/examples/01_connection/01_async_engine_basic.py
```

注意：运行前请确保 MySQL 服务已启动，且已创建 `tutorial_db` 数据库。

---

## 学习路线概览

详细的学习顺序和排序理由见 [roadmap.md](roadmap.md)。

| 阶段 | 主题 | 目录 | 你会学到 |
|------|------|------|---------|
| 1 | 连接与引擎 | `01_connection/` | create_async_engine 参数、连接池配置、池状态观察 |
| 2 | 模型定义 | `02_model_definition/` | DeclarativeBase、Mapped 类型注解、列类型与字段约束 |
| 3 | CRUD 基础 | `03_crud_basics/` | insert/select/update/delete 的 2.0 风格写法 |
| 4 | Session 生命周期 | `04_session_lifecycle/` | Session 状态机、expire_on_commit、refresh |
| 5 | 关系映射 | `05_relationships/` | 一对多、多对多、relationship 配置、MissingGreenlet 诊断 |
| 6 | 查询模式 | `06_query_patterns/` | 条件过滤、联表/子查询、分页与排序 |
| 7 | 事务管理 | `07_transactions/` | commit/rollback、savepoint 嵌套事务 |
| 8 | Repository 模式 | `08_repository_pattern/` | 泛型基类 Repository、Unit of Work、软删除与乐观锁 |
| 9 | 性能优化 | `09_performance/` | selectinload/joinedload、批量操作 |
| 10 | FastAPI 集成 | `10_fastapi_integration/` | Depends 注入 Session、完整 CRUD API |

学完示例后，阅读 `templates/` 了解如何将这些知识点封装为企业级可复用组件。

---

## 核心原则

1. **始终使用 2.0 风格** — `select()` 替代 `session.query()`，`Mapped[T]` 替代 `Column()`，这是 SQLAlchemy 的未来方向
2. **异步环境禁用 lazy loading** — 异步中访问未加载的关系会抛出 `MissingGreenlet`，必须显式使用 `selectinload` / `joinedload`；团队默认可进一步配合 `lazy="raise"` 提前 fail-fast
3. **Session 即工作单元** — 一个请求一个 Session，用完即关，不要跨请求复用
4. **expire_on_commit=False** — 异步场景下 commit 后仍需访问对象属性，默认的 expire 行为会导致 detached instance 错误
5. **连接池是生命线** — 合理配置 `pool_size`、`pool_recycle`、`pool_pre_ping`，避免连接泄漏和连接池耗尽
6. **错误映射要按约束类型细分** — `IntegrityError` 不等于“重复数据”，唯一约束、外键约束、非空约束应区分处理
7. **乐观锁要基于客户端读到的版本** — 真实 API 场景下应显式传递 `expected_version`，不要只在仓储内部读取“当前 version”；`04_optimistic_lock.py` 还会演示同一 Session 下 Core `UPDATE` 的同步陷阱，避免把被同步后的 version 误当旧快照
8. **通用 update 不应篡改系统字段** — `id` / 时间戳 / 软删除字段 / `version` 应由专门机制维护，不应通过普通 `update()` 绕过语义边界

---

## 文档说明

| 文档 | 内容 |
|------|------|
| [roadmap.md](roadmap.md) | 学习路线、排序理由、版本要求 |
| [architecture_map.md](architecture_map.md) | 异步 ORM → 企业分层架构映射 |
| [best_practices.md](best_practices.md) | 推荐做法（怎么写好） |
| [pitfalls.md](pitfalls.md) | 反模式与常见坑（怎么写错） |

---

## 学完后你应该具备的能力

- 配置生产级异步连接池，理解每个参数对性能和稳定性的影响
- 使用 SQLAlchemy 2.0 风格定义模型，抽取公共字段为 Mixin
- 在异步环境中正确管理 Session 生命周期，避免 detached instance 和连接泄漏
- 诊断 `MissingGreenlet` / `StatementError.orig`，并使用 selectinload / joinedload / `lazy="raise"` 修复异步关系加载问题
- 用 savepoint 实现部分回滚，用最小事务范围提升并发性能
- 封装泛型 Repository 和 Unit of Work，为 FastAPI 项目搭建清晰的数据访问层
- 为软删除、错误码映射、乐观锁和 request_id 设计可落地的工程边界

---

## 最后建议

数据访问层不是"能跑就行的 CRUD"，而是架构设计的一部分。好的 ORM 使用方式和好的异常体系一样，需要提前规划连接管理、Session 生命周期、事务边界和查询策略。当你开始把数据访问当作架构来思考，而不是当作 SQL 的 Python 翻译来写，代码的可维护性和性能会有质的提升。
