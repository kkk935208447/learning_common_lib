# FastAPI 教程（从入门到生产级模板）

面向有 Python 基础的开发者，系统学习 FastAPI 从路由定义到生产级接口模板的完整知识体系。

适合人群：
- 已掌握 Python 基础语法和 asyncio 基本概念
- 想系统学习 FastAPI 而非零散查文档
- 需要生产级接口模板作为项目起点

---

## 环境要求

- Python >=3.11,<3.12
- 依赖已在项目 `pyproject.toml` 中声明：fastapi, uvicorn, aiohttp, httpx, sqlalchemy, aiosqlite, pydantic, pydantic-settings, python-multipart
- 建议先完成同级 `asyncio教程/`

---

## 目录结构

```
fastapi教程/
├── README.md                          ← 你在这里
├── roadmap.md                         ← 学习路线详解
├── .gitignore
├── examples/                          ← 教学示例（服务 + 测试分离）
│   ├── 01_basics/                     3 服务 + 3 测试
│   ├── 02_request_response/           3 服务 + 3 测试
│   ├── 03_dependency_injection/       3 服务 + 3 测试
│   ├── 04_middleware_errors/          3 服务 + 3 测试
│   ├── 05_async_database/             2 服务 + 2 测试 + 1 文档
│   ├── 06_background_streaming/       3 服务 + 3 测试
│   ├── 07_auth/                       2 服务 + 2 测试
│   ├── 08_testing/                    2 服务 + 2 测试
│   ├── 09_self_exception/             3 服务 + 3 测试
│   └── 10_status_codes/               2 服务 + 2 测试 + 1 文档
```

---

## 如何运行示例

```bash
# 进入教程目录
cd src/learning_common_lib/python基础/fastapi教程

# 运行服务文件（手动探索 /docs）
uv run python examples/01_basics/01_hello_app.py

# 运行测试文件（自动验证）
uv run python examples/01_basics/01_hello_app_test.py

```

每个示例拆为两个文件：
- `xx_name.py` — 服务文件：定义 `router = APIRouter()`，可独立运行访问 `/docs`
- `xx_name_test.py` — 测试文件：导入 router，uvicorn port=0 启动，aiohttp 自动验证

---

## 学习路线概览

| 阶段 | 主题 | 目录 | 你会学到 |
|------|------|------|----------|
| 1 | 基础路由 | `01_basics/` | FastAPI 最小应用、路径参数、查询参数 |
| 2 | 请求与响应 | `02_request_response/` | Pydantic 请求体、response_model、嵌套模型 |
| 3 | 依赖注入 | `03_dependency_injection/` | Depends、yield 依赖、依赖链 |
| 4 | 中间件与错误 | `04_middleware_errors/` | 异常处理器、自定义中间件、CORS、lifespan |
| 5 | 异步数据库 | `05_async_database/` | async SQLAlchemy CRUD、Repository 模式、文件型 SQLite 持久化 |
| 6 | 后台与流式 | `06_background_streaming/` | BackgroundTasks、SSE、文件上传下载 |
| 7 | 认证 | `07_auth/` | OAuth2 密码模式、JWT Bearer |
| 8 | 测试 | `08_testing/` | TestClient 同步测试、AsyncClient 异步测试 |
| 9 | 自定义异常 | `09_self_exception/` | JSONResponse vs HTTPException、Pydantic 422、运行时异常兜底 |
| 10 | 状态码 | `10_status_codes/` | 201/202/204/400/409/422/429/502/503/504 生产级用法 |

详细学习路线见 [roadmap.md](roadmap.md)。

---

## 核心原则

1. 请求体用 Pydantic 模型，永远不要手动解析 JSON
2. 公共逻辑用 Depends 提取，保持路由函数简洁
3. response_model 过滤敏感字段，永远不要信任内部模型直接输出
4. 统一错误格式，前端只需处理一种错误结构
5. 用 lifespan 管理资源生命周期，不用已废弃的 on_event
6. 用 `fastapi.status` 常量代替裸写状态码数字，提高可读性
7. 服务与测试分离：服务文件用 `APIRouter` 定义路由，测试文件用 `aiohttp` 验证
