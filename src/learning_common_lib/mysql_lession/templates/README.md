# SQLAlchemy 异步 ORM 企业级模板包

这是一套企业级 SQLAlchemy 异步 ORM 模板包，提供从数据库引擎创建到 FastAPI 集成的完整解决方案。

## 使用方式

将 `templates/` 目录复制到你的项目中，通过环境变量 `DATABASE_URL` 配置数据库连接。表结构变更请使用 Alembic 迁移，模板默认不会在启动时自动建表。

## 模块说明

| 文件 | 说明 |
|------|------|
| `db_engine.py` | 引擎创建与连接池配置，支持单例模式和环境变量读取 |
| `db_session.py` | 异步 Session 工厂与生命周期管理（open/close），事务由调用方控制 |
| `base_model.py` | 声明式基类与公共字段混入（id、created_at、updated_at） |
| `base_repository.py` | 泛型 CRUD 仓储基类，消除重复的增删改查代码 |
| `fastapi_db_middleware.py` | FastAPI 生命周期管理与 Session 依赖注入 |

## 依赖关系

```
db_engine ← db_session
base_model ← base_repository
fastapi_db_middleware ← (db_engine, db_session, base_model)
```

箭头表示"被依赖"：`A ← B` 意味着 B 导入了 A。`fastapi_db_middleware` 是集成层，汇聚了引擎、Session 和模型三条线。

## 推荐阅读顺序

1. `db_engine.py` — 理解引擎和连接池的创建方式
2. `db_session.py` — 理解 Session 的生命周期管理
3. `base_model.py` — 理解模型基类和公共字段的设计
4. `base_repository.py` — 理解通用仓储模式如何消除重复代码
5. `fastapi_db_middleware.py` — 理解如何在 FastAPI 中集成以上所有组件
