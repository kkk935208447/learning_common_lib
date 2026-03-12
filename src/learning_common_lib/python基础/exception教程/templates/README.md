# 企业级异常处理模板

这些模板是从教程示例中提炼的可复用骨架，适合直接集成到生产项目中。

## 模板清单

| 模板 | 解决什么 | 不解决什么 |
|------|---------|-----------|
| error_registry.py | 错误码枚举注册表（唯一真源）+ 唯一性检查 | 动态注册、运行时扩展 |
| error_base.py | 项目级异常基类 + 异常树，绑定 ErrorCode，公开/内部字段分离，headers 支持 | 不替代 Python 内置异常 |
| error_context.py | 请求级错误上下文传递，token reset 支持 | 跨进程/分布式追踪 |
| fastapi_error_handler.py | FastAPI 全局异常处理器 + SuccessResponse/ErrorResponse 模型 + `success_response(...)` 显式输出 request_id + StarletteHTTPException 接管 + 日志分级 + 完整 UUID + header 透传 | 非 FastAPI 框架 |

## 异常类型决策表

| 异常类 | ErrorCode | HTTP | 记日志 | 告警 | headers |
|--------|-----------|------|--------|------|---------|
| AppValidationError | VALIDATION_ERROR | 422 | info | 否 | — |
| NotFoundError | NOT_FOUND | 404 | info | 否 | — |
| AuthenticationError | UNAUTHORIZED | 401 | info | 否 | WWW-Authenticate |
| PermissionDeniedError | FORBIDDEN | 403 | info | 否 | — |
| ConflictError | DUPLICATE | 409 | info | 否 | — |
| RateLimitedError | RATE_LIMITED | 429 | info | 否 | Retry-After |
| DatabaseError | DATABASE_ERROR | 500 | error+exc_info | 是 | — |
| ExternalServiceError | EXTERNAL_SERVICE_ERROR | 502 | error+exc_info | 是 | — |
| GatewayTimeoutError | GATEWAY_TIMEOUT | 504 | error+exc_info | 是 | — |

## 设计要点

- ErrorCode 枚举是唯一真源：code/message/status_code 全部从枚举派生
- 统一响应协议：标准 JSON 成功响应和所有错误响应都是 `{code, message, data, request_id}`，失败时 data=null 或包含 errors
- 字段分为对外（message/detail → data）和对内（internal_message/log_extra → 仅日志）
- headers 字段支持 429 Retry-After、401 WWW-Authenticate 等企业场景
- 异常命名避免与 Python 内置撞名：`PermissionDeniedError`、`AppValidationError`
- ContextVar 使用 token reset 模式，在 finally 中恢复上下文；默认上下文每次返回新对象，避免可变 extra 泄漏
- 所有内建异常（404/405 等）统一为 ErrorResponse JSON 格式
- 普通成功响应通过 `success_response(...)` 显式返回 `request_id`；异常响应仍由统一 handler 负责
- 坚持字符串错误码（NOT_FOUND 而非 40400），可读性和跨语言兼容性更好
- `204`、文件下载、真实流式响应不强行改写 body；这类响应只保证 `X-Request-ID` header

## 使用方式

templates/ 是一个 Python 包（含 `__init__.py`），从 exception教程/ 目录可直接导入：

```bash
uv run python -c "from templates import NotFoundError, RateLimitedError, success_response; print('ok')"
```

单独运行某个模板的 demo：

```bash
uv run python templates/error_base.py
```

路由里返回统一成功响应：

```python
from templates import success_response


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = {"id": user_id, "name": "alice"}
    return success_response(data=user)
```

## 重要提醒
这些模板是教学骨架，不是成熟框架。生产使用时请根据实际需求调整。
