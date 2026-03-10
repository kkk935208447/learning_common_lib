# FastAPI 教程学习路线

按顺序学习，每个阶段建立在前一阶段的基础上。

---

## 阶段 1：基础路由 (`01_basics/`)

**学什么**: FastAPI 最小应用、路由装饰器、路径参数、查询参数

**为什么在这里**: 这是一切的起点。理解路由和参数是使用任何 Web 框架的第一步。

| 文件 | 核心概念 |
|------|----------|
| `01_hello_app.py` | APIRouter、JSONResponse、uvicorn 启动 |
| `01_hello_app_test.py` | aiohttp 测试、uvicorn port=0 |
| `02_path_params.py` | 路径参数类型注解、Path() 约束、422 错误 |
| `02_path_params_test.py` | 路径参数验证测试 |
| `03_query_params.py` | 查询参数、可选参数、Query() 约束、分页 |
| `03_query_params_test.py` | 查询参数验证测试 |

**关键收获**: FastAPI 通过类型注解自动完成参数校验和文档生成。

---

## 阶段 2：请求与响应 (`02_request_response/`)

**学什么**: Pydantic 请求体校验、响应模型过滤、嵌套模型

**为什么在这里**: 掌握路由后，需要学习如何安全地接收和返回结构化数据。

| 文件 | 核心概念 |
|------|----------|
| `01_request_body.py` | BaseModel 请求体、Field 校验 |
| `01_request_body_test.py` | 请求体验证测试 |
| `02_response_model.py` | response_model 过滤敏感字段 |
| `02_response_model_test.py` | 响应模型过滤测试 |
| `03_nested_models.py` | 嵌套模型、field_validator |
| `03_nested_models_test.py` | 嵌套模型验证测试 |

**关键收获**: Pydantic 是 FastAPI 的数据层核心，请求体和响应体都应该用模型定义。

---

## 阶段 3：依赖注入 (`03_dependency_injection/`)

**学什么**: Depends 基础、yield 依赖、依赖链

**为什么在这里**: 依赖注入是 FastAPI 最强大的特性，理解它才能写出可维护的代码。

| 文件 | 核心概念 |
|------|----------|
| `01_basic_depends.py` | Depends 提取公共参数 |
| `01_basic_depends_test.py` | 依赖注入测试 |
| `02_yield_depends.py` | yield 依赖管理资源生命周期 |
| `02_yield_depends_test.py` | yield 依赖测试 |
| `03_nested_depends.py` | 依赖链：auth → user → permission |
| `03_nested_depends_test.py` | 依赖链测试 |

**关键收获**: Depends 让你把横切关注点（认证、分页、数据库）从路由中解耦。

---

## 阶段 4：中间件与错误处理 (`04_middleware_errors/`)

**学什么**: 自定义异常处理器、中间件、CORS、lifespan

**为什么在这里**: 生产应用需要统一错误格式、请求日志、跨域支持和生命周期管理。

| 文件 | 核心概念 |
|------|----------|
| `01_exception_handlers.py` | 自定义异常类 + 统一错误格式 |
| `01_exception_handlers_test.py` | 异常处理器测试 |
| `02_custom_middleware.py` | BaseHTTPMiddleware 记录耗时 |
| `02_custom_middleware_test.py` | 中间件测试 |
| `03_cors_and_hooks.py` | CORS 配置 + lifespan 上下文 |
| `03_cors_and_hooks_test.py` | CORS + lifespan 测试 |

**关键收获**: 中间件处理横切关注点，lifespan 替代了已废弃的 startup/shutdown 事件。

---

## 阶段 5：异步数据库 (`05_async_database/`)

**学什么**: async SQLAlchemy CRUD、Repository 模式

**为什么在这里**: 大多数 API 需要持久化数据，异步数据库操作是 FastAPI 的核心场景。

| 文件 | 核心概念 |
|------|----------|
| `README.md` | 文件型 SQLite 的设计说明、初始化/重置约定 |
| `01_async_sqlalchemy_crud.py` | AsyncSession + ORM CRUD + 文件型 SQLite |
| `01_async_sqlalchemy_crud_test.py` | 异步数据库 CRUD 测试 |
| `02_repository_pattern.py` | Repository 封装 + 依赖注入 + 文件型 SQLite |
| `02_repository_pattern_test.py` | Repository 模式测试 |

**关键收获**: async SQLAlchemy 配合 Depends(get_db) 是 FastAPI 数据库操作的标准模式；文件型 SQLite 比 `:memory:` 更接近真实数据库持久化行为。

---

## 阶段 6：后台任务与流式响应 (`06_background_streaming/`)

**学什么**: BackgroundTasks、SSE 流式响应、文件上传下载

**为什么在这里**: 这些是 API 开发中常见但容易出错的场景。

| 文件 | 核心概念 |
|------|----------|
| `01_background_tasks.py` | BackgroundTasks 异步任务 |
| `01_background_tasks_test.py` | 后台任务测试 |
| `02_sse_streaming.py` | StreamingResponse + SSE |
| `02_sse_streaming_test.py` | SSE 流式读取测试 |
| `03_file_upload_download.py` | UploadFile + FileResponse |
| `03_file_upload_download_test.py` | 文件上传下载测试 |

**关键收获**: BackgroundTasks 适合轻量任务，SSE 适合实时推送，大文件要分块处理。

---

## 阶段 7：认证 (`07_auth/`)

**学什么**: OAuth2 密码模式、JWT Bearer 认证

**为什么在这里**: 认证是生产 API 的必备功能，需要前面所有知识（Depends、模型、错误处理）。

| 文件 | 核心概念 |
|------|----------|
| `01_oauth2_password.py` | OAuth2PasswordBearer + 简单验证 |
| `01_oauth2_password_test.py` | OAuth2 密码模式测试 |
| `02_jwt_bearer.py` | JWT 签发与验证（stdlib 实现） |
| `02_jwt_bearer_test.py` | JWT 认证测试（含过期令牌） |

**关键收获**: OAuth2 + JWT 是最常见的 API 认证方案，FastAPI 的安全工具让实现变得简单。

---

## 阶段 8：测试 (`08_testing/`)

**学什么**: TestClient 同步测试、AsyncClient 异步测试

**为什么在这里**: 测试是保证代码质量的最后一环，也是重构的安全网。

| 文件 | 核心概念 |
|------|----------|
| `01_sync_test_client.py` | TestClient + dependency_overrides |
| `02_async_test_client.py` | httpx AsyncClient + ASGITransport |

**关键收获**: dependency_overrides 让你轻松替换依赖进行隔离测试。

---

## 阶段 9：自定义异常与企业级错误处理 (`09_self_exception/`)

**学什么**: `JSONResponse` 与 `HTTPException` 的区别、Pydantic 默认 `422`、业务异常与未知异常兜底

**为什么在这里**: 学完测试之后，需要把“错误的表达方式”系统化。企业项目不仅要让接口能跑通，还要让前端、日志和排障流程面对稳定、统一、可理解的错误结构。

| 文件 | 核心概念 |
|------|----------|
| `01_jsonresponse_vs_http_exception.py` | 正常返回 vs 异常中断、默认 `detail` 结构 |
| `01_jsonresponse_vs_http_exception_test.py` | 客户端视角观察 JSONResponse 和 HTTPException 的差异 |
| `02_pydantic_validation_422.py` | 默认 422 与公司统一 400 包装 |
| `02_pydantic_validation_422_test.py` | 观察默认 422 和统一错误结构的差别 |
| `03_self_exception_and_global_handler.py` | `BusinessException`、全局 `Exception` 兜底 |
| `03_self_exception_and_global_handler_test.py` | 客户端视角验证 200 业务错误和 500 系统错误 |

**关键收获**: `JSONResponse` 用于手动构造响应；`HTTPException` 用于中断流程；Pydantic 负责契约校验；企业项目应统一包装业务异常、校验异常和未知异常。

---
## 阶段 10：生产级状态码 (`10_status_codes/`)

**学什么**: HTTP 状态码的正确使用——201/202/204/400/404/409/422/429/502/503/504

**为什么在这里**: 学完异常处理之后，需要进一步掌握“返回什么状态码”这件事。企业项目不仅要给前端稳定的 JSON 结构，还要给监控、网关、调用方准确的 HTTP 语义。

| 文件 | 核心概念 |
|------|----------|
| `README.md` | 本章状态码设计原则、统一返回体约定 |
| `01_crud_status_codes.py` | 201 Created、204 No Content、400 vs 404 vs 409、422 |
| `01_crud_status_codes_test.py` | 客户端视角验证统一响应体和状态码 |
| `02_async_and_rate_limit.py` | 202 Accepted、429 + Retry-After、502/503/504 上游故障映射 |
| `02_async_and_rate_limit_test.py` | 客户端视角验证异步任务、限流和上游故障返回 |

**关键收获**: 状态码表达 HTTP 语义，`code/message/data` 表达业务结构；`204` 是唯一不返回 JSON body 的常见成功场景；`429` 必须带 `Retry-After`；`502/503/504` 要区分不同上游故障。

---
