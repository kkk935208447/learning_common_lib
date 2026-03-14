# TaskIQ 企业级模板

## 定位

提供生产可用的 TaskIQ 基础设施代码，可直接复制到项目中使用。

## 模块职责

| 模块 | 职责 |
|------|------|
| `taskiq_config.py` | 配置 dataclass，环境变量覆盖，broker/backend 工厂方法 |
| `taskiq_app.py` | Broker 工厂函数 + 单例管理（create / init / get） |
| `error_handling.py` | 异常层级树（TaskRetryableError / TaskFatalError），is_retryable() |
| `task_base.py` | 任务装饰器工厂 create_task()，通用包装器 safe_execute() |
| `middleware_stack.py` | LoggingMiddleware / RetryMiddleware / TimeoutMiddleware |
| `fastapi_taskiq.py` | FastAPI lifespan、get_broker Depends、send_task 辅助 |
| `__init__.py` | 公开 API 导出，FastAPI 可选依赖处理 |

## 快速开始

```python
from templates import TaskiqConfig, create_taskiq_broker, create_default_middlewares

# 1. 创建配置（自动读取环境变量）
config = TaskiqConfig()

# 2. 创建 broker（含 result_backend + 中间件）
broker = create_taskiq_broker(config)

# 3. 定义任务
@broker.task
async def process_order(order_id: int) -> dict:
    return {"order_id": order_id, "status": "done"}

# 4. 发送任务
async def main():
    await broker.startup()
    handle = await process_order.kiq(order_id=123)
    result = await handle.wait_result(timeout=30)
    print(result.return_value)
    await broker.shutdown()
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TASKIQ_BROKER_URL` | `redis://default:123456@localhost:6379/0` | Broker 连接 |
| `TASKIQ_RESULT_BACKEND_URL` | `redis://default:123456@localhost:6379/1` | Result Backend 连接 |
| `TASKIQ_RESULT_EX_TIME` | `3600` | 结果过期时间（秒） |
| `TASKIQ_CONCURRENCY` | `10` | Worker 并发数 |

## 每个模板都可独立运行

```bash
cd src/learning_common_lib/redis_lession/taskiq教程

# 运行任意模板的 _demo()
python -m templates.taskiq_config
python -m templates.taskiq_app
python -m templates.error_handling
python -m templates.task_base
python -m templates.middleware_stack
python -m templates.fastapi_taskiq
```
