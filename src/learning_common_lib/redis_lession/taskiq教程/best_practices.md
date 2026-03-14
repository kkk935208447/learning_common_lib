# 最佳实践 (Best Practices)

## 1. Broker 选型

- **ListQueueBroker**（推荐默认）：基于 Redis List，竞争消费，适合任务队列场景
- **PubSubBroker**：基于 Redis Pub/Sub，广播模式，适合事件通知、缓存失效
- 不确定时选 ListQueueBroker，它覆盖 90% 的任务队列需求

```python
# ✅ 推荐：任务队列用 ListQueueBroker
from taskiq_redis import ListQueueBroker
broker = ListQueueBroker(url="redis://default:123456@localhost:6379/0")

# ✅ 广播场景用 PubSubBroker
from taskiq_redis import PubSubBroker
pubsub = PubSubBroker(url="redis://default:123456@localhost:6379/0")
```

## 2. Result Backend 配置

- 不是所有任务都需要结果，不需要结果时不配置 result_backend 可减少 Redis 写入
- `result_ex_time` 必须设置，否则结果永不过期，Redis 内存持续增长
- 推荐 `result_ex_time=3600`（1 小时），根据业务调整

```python
# ✅ 设置过期时间
backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
    result_ex_time=3600,  # 1 小时后自动清理
)
```

## 3. 中间件顺序

中间件按注册顺序执行，推荐顺序：

1. **LoggingMiddleware** — 最外层，记录所有请求
2. **RetryMiddleware** — 在日志之后，错误处理之前
3. **TimeoutMiddleware** — 最内层，超时控制

```python
broker = broker.with_middlewares(
    LoggingMiddleware(),   # 第一个执行
    RetryMiddleware(),     # 第二个执行
    TimeoutMiddleware(),   # 第三个执行
)
```

## 4. 依赖注入粒度

- 每个依赖函数只做一件事（单一职责）
- 使用 async generator 依赖管理资源生命周期（自动 cleanup）
- 避免在依赖中做重计算，依赖每次任务执行都会调用

```python
# ✅ 推荐：async generator 自动管理资源
async def get_db_session():
    session = await create_session()
    try:
        yield session
    finally:
        await session.close()

# ❌ 避免：在依赖中做重计算
async def get_heavy_model():
    return load_ml_model()  # 每次任务都加载，太慢
```

## 5. 错误处理策略

- 区分可重试异常和致命异常（使用 `templates/error_handling.py` 的异常层级）
- 可重试异常：网络超时、限流、临时资源不可用
- 致命异常：数据格式错误、业务逻辑错误、权限不足
- 使用 `is_retryable(exc)` 统一判断

```python
# ✅ 推荐：异常分类
if is_retryable(error):
    # 重试：指数退避
    await asyncio.sleep(delay)
    await broker.kick(message)
else:
    # 致命：记录日志，不重试
    logger.error(f"致命错误: {error}")
```

## 6. Labels 使用规范

- labels 是任务的元数据，中间件可读取
- 用于：队列路由、优先级、重试配置、超时设置
- 命名约定：业务标签用小写下划线，内部标签用 `_` 前缀

```python
# ✅ 推荐：通过 labels 配置重试
@broker.task(
    queue="high_priority",
    max_retries=5,
    retry_delay=2.0,
    timeout=60,
)
async def important_task(data: dict) -> dict:
    ...
```

## 7. 定时任务管理

- 调度器（scheduler）和 worker 是独立进程，分别启动
- 使用 `RedisScheduleSource` 持久化调度配置
- 动态调度优先用 `source.add_schedule()` API，避免硬编码

```bash
# 终端 1: 启动 worker
taskiq worker myapp:broker

# 终端 2: 启动调度器
taskiq scheduler myapp:scheduler
```

## 8. FastAPI 集成

- 在 lifespan 中调用 `broker.startup()` / `broker.shutdown()`
- 无需 `taskiq-fastapi` 包，手动集成更灵活可控
- 共享依赖函数：定义一次，FastAPI Depends 和 TaskIQ TaskiqDepends 都用

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.startup()
    yield
    await broker.shutdown()
```

## 9. Worker 部署

- 生产环境使用多 worker 实例，通过队列隔离不同优先级
- 监控 worker 健康状态，异常退出时自动重启（systemd / supervisor）
- 设置合理的并发数，避免 worker 过载

```bash
# 高优先级 worker
taskiq worker myapp:broker --tasks-pattern "high_priority"

# 批处理 worker
taskiq worker myapp:broker --tasks-pattern "batch"
```

## 10. 客户端侧 broker.startup()

- 客户端（发送任务的进程）也需要调用 `broker.startup()` 初始化连接
- 忘记调用是最常见的错误之一
- 使用完毕后调用 `broker.shutdown()` 释放连接

```python
async def main():
    await broker.startup()  # 必须！
    try:
        await my_task.kiq(data)
    finally:
        await broker.shutdown()  # 清理
```

## 11. 序列化注意

- TaskIQ 默认使用 JSON 序列化，任务参数和返回值必须是 JSON 可序列化的
- 避免传递复杂对象（ORM 模型、文件句柄等），传 ID 让 worker 自己查询
- 大数据不要通过消息传递，存到 S3/数据库，只传引用

```python
# ✅ 推荐：传 ID
await process_order.kiq(order_id=12345)

# ❌ 避免：传复杂对象
await process_order.kiq(order=order_orm_object)
```

## 12. 幂等性设计

- 任务可能因重试而多次执行，确保任务逻辑幂等
- 使用唯一业务 ID 做去重（如订单号）
- 数据库操作使用 upsert 而非 insert

```python
@broker.task
async def process_payment(payment_id: str) -> dict:
    # ✅ 幂等：先查是否已处理
    existing = await db.get_payment(payment_id)
    if existing and existing.status == "completed":
        return {"status": "already_processed"}
    # 处理支付...
```
