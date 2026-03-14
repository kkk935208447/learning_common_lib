# 常见陷阱 (Pitfalls)

## 1. 忘记调用 broker.startup()

**现象**: 发送任务时报错 `ConnectionError` 或任务发送后无响应。

**原因**: TaskIQ 的 broker 需要显式初始化连接，不像 Celery 在首次使用时自动连接。

```python
# ❌ 错误：直接发送任务
await my_task.kiq(data)  # ConnectionError!

# ✅ 正确：先 startup
await broker.startup()
await my_task.kiq(data)
await broker.shutdown()
```

**影响范围**: 客户端和 worker 都需要。Worker 由 `taskiq worker` 命令自动处理，但客户端脚本必须手动调用。

## 2. 同步阻塞 async worker

**现象**: Worker 吞吐量极低，任务排队严重。

**原因**: 在 async 任务中调用了同步阻塞操作（如 `time.sleep()`、同步 HTTP 请求、同步数据库查询）。

```python
# ❌ 错误：同步阻塞
@broker.task
async def bad_task():
    time.sleep(10)  # 阻塞整个事件循环！
    requests.get("https://api.example.com")  # 同步 HTTP！

# ✅ 正确：使用 async 库
@broker.task
async def good_task():
    await asyncio.sleep(10)
    async with httpx.AsyncClient() as client:
        await client.get("https://api.example.com")
```

**对比 Celery**: Celery prefork worker 每个进程独立，同步阻塞只影响当前进程。TaskIQ 是单线程事件循环，一个阻塞影响所有任务。

## 3. 依赖注入循环引用

**现象**: Worker 启动时报错 `RecursionError` 或依赖解析超时。

**原因**: 依赖 A 依赖 B，B 又依赖 A，形成循环。

```python
# ❌ 错误：循环依赖
async def get_a(b = TaskiqDepends(get_b)):
    return {"a": True, "b": b}

async def get_b(a = TaskiqDepends(get_a)):  # 循环！
    return {"b": True, "a": a}

# ✅ 正确：提取公共依赖
async def get_config():
    return {"shared": True}

async def get_a(config = TaskiqDepends(get_config)):
    return {"a": True, **config}

async def get_b(config = TaskiqDepends(get_config)):
    return {"b": True, **config}
```

## 4. Result Backend 内存泄漏

**现象**: Redis 内存持续增长，最终 OOM。

**原因**: 配置了 result_backend 但未设置 `result_ex_time`，任务结果永不过期。

```python
# ❌ 错误：未设置过期时间
backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)

# ✅ 正确：设置过期时间
backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
    result_ex_time=3600,  # 1 小时后自动清理
)
```

**排查**: `redis-cli -a 123456 -n 1 DBSIZE` 查看 key 数量是否持续增长。

## 5. PubSubBroker vs ListQueueBroker 混淆

**现象**: 同一条消息被多个 worker 重复处理，或者消息丢失。

**原因**: 错误地使用了 PubSubBroker 做任务队列。

```python
# ❌ 错误：用 PubSub 做任务队列（所有 worker 都会收到）
from taskiq_redis import PubSubBroker
broker = PubSubBroker(url=...)  # 广播模式！

# ✅ 正确：任务队列用 ListQueueBroker
from taskiq_redis import ListQueueBroker
broker = ListQueueBroker(url=...)  # 竞争消费
```

**选型原则**:
- 任务处理（每条消息只处理一次）→ ListQueueBroker
- 事件通知（所有订阅者都收到）→ PubSubBroker

## 6. with_result_backend() 返回新对象

**现象**: 配置了 result_backend 但 `wait_result()` 超时，拿不到结果。

**原因**: `broker.with_result_backend()` 返回新的 broker 对象，原对象不变。

```python
# ❌ 错误：忽略返回值
broker = ListQueueBroker(url=...)
broker.with_result_backend(backend)  # 返回值被丢弃！

# ✅ 正确：重新赋值
broker = ListQueueBroker(url=...)
broker = broker.with_result_backend(backend)  # 使用新对象
```

同理 `with_middlewares()` 也返回新对象。

## 7. 任务参数不可序列化

**现象**: 发送任务时报 `TypeError: Object of type X is not JSON serializable`。

**原因**: TaskIQ 默认使用 JSON 序列化，不支持复杂 Python 对象。

```python
# ❌ 错误：传 ORM 对象
await process_user.kiq(user=user_orm_object)

# ❌ 错误：传 datetime 对象
await schedule_task.kiq(run_at=datetime.now())

# ✅ 正确：传基本类型
await process_user.kiq(user_id=user.id)
await schedule_task.kiq(run_at=datetime.now().isoformat())
```

## 8. Worker 和 Client 的 broker 对象不一致

**现象**: 客户端发送的任务 worker 收不到，或者 worker 报 "unknown task"。

**原因**: Worker 启动时指定的 broker 模块和客户端使用的不是同一个。

```bash
# Worker 使用的 broker
taskiq worker myapp.broker:broker

# 客户端必须 import 同一个 broker 对象
from myapp.broker import broker
```

## 9. 中间件 on_error 中重新发送导致无限循环

**现象**: 任务不断重试，永不停止，Redis 队列堆积。

**原因**: 重试中间件没有设置最大重试次数，或者重试计数器没有正确递增。

```python
# ❌ 错误：无限重试
async def on_error(self, message, result, error):
    await self.broker.kick(message)  # 永远重试！

# ✅ 正确：限制重试次数
async def on_error(self, message, result, error):
    retry_count = message.labels.get("_retry_count", 0)
    max_retries = message.labels.get("max_retries", 3)
    if retry_count < max_retries:
        message.labels["_retry_count"] = retry_count + 1
        await self.broker.kick(message)
    else:
        logger.error(f"重试耗尽: {error}")
```

## 10. 忘记在 FastAPI lifespan 中管理 broker

**现象**: FastAPI 应用启动后发送任务失败，或关闭时连接泄漏。

**原因**: 没有在 lifespan 中调用 `broker.startup()` / `broker.shutdown()`。

```python
# ❌ 错误：没有 lifespan 管理
app = FastAPI()

# ✅ 正确：lifespan 管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.startup()
    yield
    await broker.shutdown()

app = FastAPI(lifespan=lifespan)
```

## 11. wait_result() 不设置 timeout

**现象**: 客户端永久挂起，等待一个永远不会完成的任务。

**原因**: `wait_result()` 默认无超时，如果 worker 崩溃或任务丢失，客户端永远等待。

```python
# ❌ 错误：无超时
result = await handle.wait_result()  # 可能永远等待

# ✅ 正确：设置超时
result = await handle.wait_result(timeout=30)
```

## 12. 在任务中直接 import 重量级模块

**现象**: Worker 启动慢，内存占用高。

**原因**: 在模块顶层 import 了 ML 模型、大型数据集等。

```python
# ❌ 错误：顶层 import 重量级模块
import tensorflow as tf  # Worker 启动时就加载
model = tf.keras.models.load_model("big_model.h5")

# ✅ 正确：在 startup 事件中加载，通过 State 共享
@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState):
    import tensorflow as tf
    state.model = tf.keras.models.load_model("big_model.h5")
```
