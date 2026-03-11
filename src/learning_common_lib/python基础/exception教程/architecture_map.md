# 架构映射（architecture_map）— 异常处理在企业分层架构中的角色

本文档说明异常处理如何映射到真实企业分层架构的各个层。

---

## 企业级分层架构

```text
┌─────────────────────────────────────────────┐
│         客户端 (Client)                      │
├─────────────────────────────────────────────┤
│      异常处理器层 (Exception Handler)         │
│  全局异常处理器 / 统一 JSON 响应              │
├─────────────────────────────────────────────┤
│        控制器层 (Controller/Router)           │
│  路由函数 / 不做异常处理，只调用 Service       │
├─────────────────────────────────────────────┤
│         服务层 (Service)                     │
│  业务逻辑 / 异常转换边界                      │
├─────────────────────────────────────────────┤
│       仓储层 (Repository)                    │
│  数据访问 / 捕获底层异常 → raise from         │
├─────────────────────────────────────────────┤
│       基础设施 (Infrastructure)               │
│  数据库 / 外部 API / 文件系统                 │
└─────────────────────────────────────────────┘
```

---

## 知识点 → 架构层 → 教程文件 → 模板

| 架构层 | 异常处理职责 | 教程示例 | 企业模板 |
|--------|-------------|---------|---------|
| 基础设施层 | 抛出原始异常 | — | — |
| 仓储层 | 捕获底层异常 → `raise XxxError from e` | `07_deep_call_stack/01` | `error_base.py` |
| 服务层 | 业务判断 → `raise BusinessError` / 透传 | `07_deep_call_stack/01` | `error_base.py` |
| 控制器层 | 不做异常处理，让异常冒泡 | `08_fastapi_error_architecture/01` | — |
| 异常处理器层 | AppError→统一JSON, Exception→500+日志 | `08_fastapi_error_architecture/01` | `fastapi_error_handler.py` |

---

## 每一层的异常处理规则

### 基础设施层（硬规则）

- **不记日志，不做任何异常处理**
- 数据库驱动、HTTP 客户端、文件系统抛出原始异常
- 这些异常不应该直接暴露给上层业务代码
- 日志由上层决定记还是不记

### 仓储层（Repository）（硬规则）

- **只捕获明确的库异常**（如 `asyncpg.PostgresError`），不要 `except Exception`
- 必须使用 `raise from` 保留原始异常链
- 转换后的异常应该是项目异常树中的具体类型
- 可用 `add_note()` 补充定位信息（user_id 等）

```python
try:
    row = await db.fetch_one(query)
except asyncpg.PostgresError as e:
    err = UserNotFoundError(user_id=user_id)
    err.add_note(f"查询用户 user_id={user_id} 时发生")
    raise err from e
```

### 服务层（Service）（硬规则）

- **不做大包围 `except Exception`**
- 做业务判断，抛出业务异常（如 `InsufficientBalanceError`）
- 对仓储层抛出的领域异常：透传或包装为更高层的业务异常
- 可用 `add_note()` 补充业务上下文（order_id 等）

```python
def transfer(from_id, to_id, amount):
    account = repo.get_account(from_id)  # 可能抛 AccountNotFoundError
    if account.balance < amount:
        raise InsufficientBalanceError(
            account_id=from_id, balance=account.balance, required=amount
        )
```

### 控制器层（Controller/Router）（硬规则）

- **不做异常处理**
- 只负责调用 Service 层，让异常自然冒泡到异常处理器层
- 这是最容易犯错的地方 — 很多人在这里加 try/except，导致异常处理逻辑分散

```python
@router.post("/transfer")
async def transfer(req: TransferRequest):
    result = service.transfer(req.from_id, req.to_id, req.amount)
    return {"code": "OK", "message": "success", "data": result}
    # 不需要 try/except，异常会被全局处理器捕获
```

### 异常处理器层（Exception Handler）（硬规则）

- 全局注册，统一处理所有异常，**记录最终日志**
- `ClientError`（4xx）→ `logger.info`，不带 exc_info
- `ServerError`（5xx）→ `logger.error` + `exc_info=True`，记录 internal_message + log_extra
- 未知 `Exception` → `logger.error` + `exc_info=True` → 返回 500 + 通用错误信息
- `StarletteHTTPException`（404/405 等）→ 统一 ErrorResponse JSON
- 响应只包含对外字段：code/message/data/request_id（通过 ErrorResponse 模型约束）
- 标准 JSON 成功响应和所有错误响应共享同一协议：`{code, message, data, request_id}`
- AppError.headers 透传到响应头（如 Retry-After、WWW-Authenticate）
- **绝不暴露内部细节给客户端**（internal_message、log_extra、traceback、SQL 等）
- `204`、文件下载、真实流式响应只保证 `X-Request-ID` header，不强行改写 body

```python
@app.exception_handler(AppError)
async def handle_app_error(request, exc):
    body = ErrorResponse(
        code=exc.code,
        message=exc.display_message,
        data=exc.detail,
        request_id=ctx.request_id,
    )
    return _build_response(exc.status_code, body, exc.headers)
```

---

## 异常类型 → HTTP 状态码 → 日志/告警/headers 决策表

| 异常类 | HTTP | 记日志 | 告警 | headers | handler |
|--------|------|--------|------|---------|---------|
| AppValidationError | 422 | info | 否 | — | AppError handler |
| NotFoundError | 404 | info | 否 | — | AppError handler |
| AuthenticationError | 401 | info | 否 | WWW-Authenticate | AppError handler |
| PermissionDeniedError | 403 | info | 否 | — | AppError handler |
| ConflictError | 409 | info | 否 | — | AppError handler |
| RateLimitedError | 429 | info | 否 | Retry-After | AppError handler |
| DatabaseError | 500 | error+exc_info | 是 | — | AppError handler |
| ExternalServiceError | 502 | error+exc_info | 是 | — | AppError handler |
| GatewayTimeoutError | 504 | error+exc_info | 是 | — | AppError handler |
| StarletteHTTPException | 4xx/5xx | — | — | — | Starlette handler |
| RequestValidationError | 422 | — | 否 | — | Validation handler |
| Exception（兜底） | 500 | error+exc_info | 是 | — | Exception handler |

---

## 日志应该记在哪一层

| 层 | 日志级别 | 记什么 |
|----|---------|--------|
| 基础设施层 | — | 不记（由上层决定） |
| 仓储层 | `DEBUG` | 转换前的原始异常信息（开发调试用） |
| 服务层 | — | 不记（异常透传到处理器层） |
| 控制器层 | — | 不记（不处理异常） |
| 异常处理器层 | `INFO`/`ERROR` | ClientError→info(path+method+code)；ServerError/Exception→error(traceback+request_id+internal_message) |

原则：每个异常只在一个地方记录日志，避免同一个错误在日志里出现 3 遍。

---

## request_id 如何贯穿全链路

```text
客户端请求
  │
  ▼
中间件：生成 request_id → 存入 request.state
  │
  ▼
控制器 → 服务 → 仓储 → 基础设施
  │                        │
  │                        ▼ 异常发生
  │                   raise XxxError from e
  │              ◄─── 异常冒泡 ───┘
  ▼
异常处理器：从 request.state 取 request_id → 写入日志 → 写入响应 JSON
  │
  ▼
客户端收到：{"code": "USER_NOT_FOUND", "message": "用户不存在", "data": null, "request_id": "abc-123"}
```

客户端拿到 request_id 后可以直接提供给运维，运维用 request_id 在日志系统中搜索完整链路。

---

## 对比图：混乱的做法 vs 清晰的做法

### 混乱的做法

```text
Controller:
  try:
      result = service.transfer(...)
  except Exception as e:
      logger.error(f"Transfer failed: {e}")     # 日志 #1
      return {"error": str(e)}                   # 暴露内部细节

Service:
  try:
      account = repo.get_account(user_id)
  except Exception as e:
      logger.error(f"Get account failed: {e}")   # 日志 #2（重复）
      raise RuntimeError(f"failed: {e}")          # 丢失原始 traceback

Repository:
  try:
      row = db.fetch(query)
  except Exception as e:
      logger.error(f"DB error: {e}")              # 日志 #3（又重复）
      raise                                        # 原始异常直接暴露

问题：
- 同一个错误记了 3 遍日志
- 原始 traceback 在 Service 层被丢弃
- 客户端看到内部实现细节
- 没有 request_id，无法关联日志
- 没有错误码，客户端无法程序化处理
```

### 清晰的做法

```text
ExceptionHandler:
  AppError     → {"code": "USER_NOT_FOUND", "message": "用户不存在", "data": null, "request_id": "abc-123"}
  Exception    → logger.error(traceback + request_id)
               → {"code": "INTERNAL_ERROR", "message": "服务器内部错误", "data": null, "request_id": "abc-123"}

Controller:
  # 不做异常处理
  result = service.transfer(...)
  return {"code": "OK", "message": "success", "data": result}
  # request_id 由中间件统一补齐到标准 JSON 响应体

Service:
  account = repo.get_account(user_id)    # 异常自然冒泡
  if account.balance < amount:
      raise InsufficientBalanceError(...)  # 业务异常

Repository:
  try:
      row = db.fetch(query)
  except asyncpg.PostgresError as e:
      raise UserNotFoundError(user_id=user_id) from e  # 转换 + 保留链

优点：
- 每个异常只记一次日志（在异常处理器层）
- 完整异常链保留（raise from）
- 客户端只看到结构化错误信息
- request_id 贯穿全链路
- 错误码可程序化处理
```

---

## 从教程到生产的演进路径

1. 先用示例理解每个概念的边界和行为（01-07 章）
2. 用第 08 章理解如何将概念组合为完整的错误架构
3. 阅读 `templates/` 了解如何将架构封装为可复用组件
4. 在实际项目中按架构层组合模板，根据业务需求扩展：添加错误码国际化、错误聚合告警、错误率监控等
