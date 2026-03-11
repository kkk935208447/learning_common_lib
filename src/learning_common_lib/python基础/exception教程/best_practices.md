# 异常处理最佳实践

这份文档只讲"推荐做法"。反模式和常见错误见 [pitfalls.md](pitfalls.md)。

---

## 1. 永远使用 raise from 保留异常链

```python
# 正确
try:
    row = db.fetch(query)
except DatabaseError as e:
    raise UserNotFoundError(user_id=user_id) from e

# 错误 — 丢失原始 traceback
except DatabaseError as e:
    raise RuntimeError(f"查询失败: {e}")
```

`raise from` 会在异常对象上设置 `__cause__`，traceback 会完整打印两层异常链。

---

## 2. 在边界层转换异常，不在每一层都 catch

异常转换只在两个地方做：

- **仓储层**：基础设施异常 → 领域异常
- **服务层**：领域异常 → 业务异常（如果需要）

控制器层不做异常处理，让异常冒泡到全局异常处理器。

---

## 3. 自定义异常拆分公开信息与内部排障信息

```python
class AppError(Exception):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str | None = None,       # 对外：用户可读（默认从 ErrorCode 取）
        detail: dict | None = None,       # 对外：结构化信息（如 {"field": "email"}）
        internal_message: str | None = None,  # 对内：排障信息（SQL、表名等）
        log_extra: dict | None = None,    # 对内：日志附加数据
        headers: dict[str, str] | None = None,  # 附加响应头（Retry-After 等）
    ):
        ...
```

对外字段（message/detail）进入 HTTP 响应的 data 字段，对内字段（internal_message/log_extra）仅写入日志。
headers 字段支持 429 Retry-After、401 WWW-Authenticate 等企业场景。
避免底层 SQL、表名、上游报文泄露给客户端。

---

## 4. 设计项目级异常树

```python
AppError                          # 项目根异常
├── ClientError                   # 4xx 客户端错误
│   ├── AppValidationError        # 422 参数校验失败（避免与 Pydantic 撞名）
│   ├── NotFoundError             # 404 资源不存在
│   ├── AuthenticationError       # 401 未认证（可带 WWW-Authenticate header）
│   ├── PermissionDeniedError     # 403 权限不足（避免与内置 PermissionError 撞名）
│   ├── ConflictError             # 409 资源冲突
│   └── RateLimitedError          # 429 请求过频（可带 Retry-After header）
└── ServerError                   # 5xx 服务端错误
    ├── DatabaseError             # 500 数据库错误
    ├── ExternalServiceError      # 502 外部服务错误
    └── GatewayTimeoutError       # 504 网关超时
```

好处：上层可以 `except ClientError` 一次性捕获所有客户端错误，也可以精确捕获 `NotFoundError`。

---

## 5. 用 logging.exception() 记录异常，不用 print

```python
import logging

logger = logging.getLogger(__name__)

try:
    process()
except SomeError:
    # 正确 — 自动附带完整 traceback
    logger.exception("处理失败, user_id=%s", user_id)

    # 错误 — 没有 traceback，生产环境无法调试
    # print(f"处理失败: {e}")
```

`logging.exception()` 等价于 `logging.error(..., exc_info=True)`，会自动记录完整的异常栈。

---

## 6. 精确捕获异常类型，不要 except Exception

```python
# 正确 — 只捕获预期的异常
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    return default_value

# 错误 — 会把 KeyboardInterrupt 以外的所有异常都吞掉
try:
    data = json.loads(raw)
except Exception:
    return default_value
```

`except Exception` 只在全局异常处理器中使用，业务代码中应该精确捕获。

---

## 7. 统一错误响应格式（ErrorResponse 模型）

```python
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    code: str                          # 机器可读的错误码
    message: str                       # 人类可读的信息
    data: dict | list | None = None    # 成功时为业务数据，失败时为 null 或 errors
    request_id: str = "no-request"     # 链路追踪 ID

# 成功响应
return {"code": "OK", "message": "success", "data": user, "request_id": rid}

# 错误响应
body = ErrorResponse(code="USER_NOT_FOUND", message="用户不存在", request_id=rid)
return JSONResponse(status_code=404, content=body.model_dump())
```

标准 JSON 成功响应和错误响应共享 `code + message + data + request_id` 协议；在 FastAPI 模板里，中间件会为符合该结构的普通成功 JSON 自动补齐 `request_id`。
`204`、文件下载、真实流式响应不强行改写 body，这些场景通过 `X-Request-ID` header 贯穿链路。
客户端根据 `code` 做程序化处理，用户看到 `message`，运维用 `request_id` 查日志。

---

## 8. 错误码使用枚举管理，保证唯一性

```python
from enum import Enum

class ErrorCode(str, Enum):
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
```

枚举保证错误码不会重复，IDE 可以自动补全，重构时也不会遗漏。

---

## 9. 区分客户端错误和服务端错误

| 类型 | HTTP 状态码 | 是否记日志 | 是否告警 | 示例 |
|------|------------|-----------|---------|------|
| 客户端错误 | 4xx | 通常不记 | 不告警 | 参数错误、资源不存在、权限不足 |
| 服务端错误 | 5xx | 必须记 | 需要告警 | 数据库连接失败、外部服务超时 |

不要把客户端错误当成服务端错误处理，否则日志和告警会被淹没。

---

## 10. 在 finally 中只做清理，不要有业务逻辑

```python
# 正确
try:
    conn = open_connection()
    result = conn.execute(query)
except DatabaseError:
    logger.exception("查询失败")
    raise
finally:
    conn.close()  # 只做资源清理

# 错误 — finally 中的 return 会吞掉异常
try:
    result = process()
finally:
    return default_value  # 异常被静默吞掉！
```

---

## 11. 用上下文管理器管理资源，不要手动 try/finally

```python
# 正确 — 上下文管理器自动处理清理
with open("data.txt") as f:
    data = f.read()

# 不推荐 — 手动管理容易遗漏
f = open("data.txt")
try:
    data = f.read()
finally:
    f.close()
```

对于自定义资源，实现 `__enter__` / `__exit__` 或使用 `contextlib.contextmanager`。

---

## 12. 生产级代码自查清单

提交异常处理相关代码前，确认：

- [ ] 没有 `except: pass` 或 `except Exception: pass`
- [ ] 所有异常转换都使用了 `raise from`
- [ ] 自定义异常继承自项目根异常（不是直接继承 `BaseException`）
- [ ] 异常只在边界层转换，不在每一层都 catch
- [ ] 日志只记一次，不重复记录
- [ ] 客户端错误和服务端错误有区分
- [ ] 响应格式统一（code + message + data + request_id）
- [ ] finally 块中没有 return 语句
- [ ] 资源管理使用上下文管理器
- [ ] 不向客户端暴露内部实现细节（traceback、SQL 语句等）

---

## 13. 使用 add_note() 在传播过程中补充上下文（Python 3.11+）

```python
# 仓储层：边界转换 + add_note
try:
    row = db.fetch(query)
except asyncpg.PostgresError as e:
    err = UserNotFoundError(user_id=user_id)
    err.add_note(f"查询用户 user_id={user_id} 时发生")
    raise err from e

# 服务层：透传异常，补充业务上下文
try:
    user = repo.get_user(user_id)
except UserNotFoundError:
    import sys
    exc = sys.exc_info()[1]
    if exc is not None:
        exc.add_note(f"处理订单 order_id={order_id} 时触发")
    raise
```

`add_note()` 的优势：不破坏原始异常链（不需要再包装一层），traceback 末尾会打印所有 note，
方便在生产日志中快速定位是哪个用户、哪个订单触发了异常。
