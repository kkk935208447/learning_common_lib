# TaskIQ 企业级模板

## 定位

提供生产可用的 TaskIQ 基础设施代码，可直接复制到项目中使用。

模板层约定：

- 优先保留薄封装，避免把教学演示逻辑混入生产骨架
- 默认值强调稳定性和可读性，不追求过度抽象
- 每个模块都保留 `_demo()`，方便 smoke 和人工单独验证
- 当前模板主线默认使用 `ListQueueBroker`；如果你需要 `RedisStreamBroker` 的 ACK / reclaim / Consumer Group 能力，
  请先阅读 `examples/08_redis_stream_broker/`

## 模块职责

| 模块 | 职责 |
|------|------|
| `taskiq_config.py` | 配置 dataclass，环境变量覆盖，broker/backend 工厂方法 |
| `taskiq_app.py` | Broker 工厂函数 + 单例管理 + `broker_session()` |
| `error_handling.py` | 异常层级树（TaskRetryableError / TaskFatalError），is_retryable() |
| `task_base.py` | 任务装饰器工厂 create_task()，稳定默认 task_name，通用包装器 safe_execute() |
| `middleware_stack.py` | LoggingMiddleware / RetryMiddleware / SlowTaskWarningMiddleware |
| `fastapi_taskiq.py` | FastAPI lifespan、get_broker Depends、send_task 辅助 |
| `__init__.py` | 公开 API 导出，FastAPI 可选依赖处理 |

## 快速开始

```python
from templates import (
    TaskiqConfig,
    broker_session,
    create_default_middlewares,
    create_taskiq_broker,
)

# 1. 创建配置（自动读取环境变量）
config = TaskiqConfig()

# 2. 创建 broker（默认只组装 result_backend）
broker = create_taskiq_broker(config)
broker = broker.with_middlewares(*create_default_middlewares())

# 3. 定义任务
@broker.task
async def process_order(order_id: int) -> dict:
    return {"order_id": order_id, "status": "done"}

# 4. 发送任务
async def main():
    async with broker_session(broker):
        handle = await process_order.kiq(order_id=123)
        result = await handle.wait_result(timeout=30)
        print(result.return_value)
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TASKIQ_BROKER_URL` | `redis://default:123456@localhost:6379/0` | Broker 连接 |
| `TASKIQ_QUEUE_NAME` | `taskiq:default` | Broker 监听的逻辑队列名 |
| `TASKIQ_RESULT_BACKEND_URL` | `redis://default:123456@localhost:6379/1` | Result Backend 连接 |
| `TASKIQ_RESULT_EX_TIME` | `3600` | 结果过期时间（秒） |

Worker 并发、threadpool、大型 CPU 任务建议通过 `taskiq worker` CLI 参数控制，而不是塞进 Broker 配置对象。

如果业务需要更可靠的 Redis 队列语义：

- 当前教程主线模板仍然保持 `ListQueueBroker`
- `RedisStreamBroker` 的详细知识点和路由方式请参考 `examples/08_redis_stream_broker/`

`broker_session(...)` 更适合作为模板层和中后期教程里的收敛写法；前期教程仍然建议先理解显式 `startup()` / `shutdown()`。

## 关键默认约定

- `create_task(...)` 默认会生成稳定的 `task_name="<module>.<func_name>"`，避免跨模块撞名
- `safe_execute(...)` 同时支持 `sync def` 和 `async def`
- `RetryMiddleware` / `SlowTaskWarningMiddleware` 对脏 labels 会回退到默认值，而不是直接把任务打崩
- `TaskiqConfig.create_broker()` 会显式传入 `queue_name`，不依赖 TaskIQ 默认队列 `taskiq`
- 同一组同构 worker 共享一个队列用于扩容是正常模式
- 不同服务不要共享同一个默认队列；至少通过 `TASKIQ_QUEUE_NAME` 做服务级隔离

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
