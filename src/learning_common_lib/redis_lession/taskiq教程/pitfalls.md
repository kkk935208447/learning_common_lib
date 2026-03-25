# 常见陷阱 (Pitfalls)

## 1. 忘记调用 `broker.startup()`

**现象**: 发送任务时报错 `ConnectionError`，或者任务发送后无响应。

**原因**: TaskIQ 的 broker 需要显式初始化连接，不像 Celery 在首次使用时自动连接。

```python
# ❌ 错误：直接发送任务
await my_task.kiq(data)

# ✅ 正确：先 startup
await broker.startup()
await my_task.kiq(data)
await broker.shutdown()
```

**影响范围**:
- 客户端脚本必须手动调用
- `taskiq worker` / `taskiq scheduler` 命令会自动处理自身生命周期

## 2. 队列冲突消费导致任务被“吃掉”

这是当前目录里最容易误判的问题，也是最值得优先记住的一条。

**现象**:
- client 成功打印 `task_id`，但 `wait_result()` 一直超时
- 重启电脑或杀掉后台 worker 之后，现象暂时消失
- 同一个 Redis 实例上跑了多个 TaskIQ worker，看起来都“连通正常”，但任务偶发丢失

**先澄清一个前提**:
- 单个 worker 完全可以在一个队列里处理多个不同 `task_name`
- 多个 worker 共享同一个队列也完全可以，这是标准的横向扩容方式
- 真正有问题的是：这些 worker 监听了同一个队列，但它们注册的任务集合并不一致

**错误认知**:
- “只要队列一样，任何 worker 都能安全混在一起”
- “只要 `task_name` 不同，共享同一个队列也天然没问题”

**真实原因**:
- `ListQueueBroker` 底层使用 Redis `LPUSH / BRPOP`
- Redis 会先把消息从 `queue_name` 对应的 list 里弹出
- 某个 worker 抢到消息之后，TaskIQ 才在 worker 本地执行 `find_task(task_name)`
- 如果这个 worker 没注册对应任务，它只会记日志并丢弃消息，不会自动 requeue

也就是说：

- `queue_name` 决定“谁有资格先抢到消息”
- `task_name` 决定“抢到消息之后，本地能不能找到对应函数”

`task_name` 不是 broker 层隔离条件。

**最小复现**:

```python
# worker_a.py
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name="taskiq",
)

@broker.task(task_name="a.send_email")
async def send_email():
    ...
```

```python
# worker_b.py
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name="taskiq",
)

@broker.task(task_name="b.process_order")
async def process_order():
    ...
```

如果 `worker_b` 先从同一个 `taskiq` 队列里抢到 `a.send_email` 的消息，它会发现本地没有这个任务，然后直接丢弃。

反过来说：
- 如果 `worker_a` 和 `worker_b` 都注册了 `a.send_email`，那它们共享同一个队列就是正常的竞争消费
- 问题不在于“多个 worker”，而在于“多个不兼容的 worker”

**再补一条很容易混淆的边界**:
- `ListQueueBroker` 也支持 producer 侧 `queue_name` 动态路由
- 但这不等于“一个 worker 可以同时监听多个 queue”
- 原因很直接：`kick()` 会根据 `labels["queue_name"]` 选择写入哪个 list，
  但 `listen()` 仍然只会 `BRPOP(self.queue_name)`
- 所以对 `ListQueueBroker` 来说：
  - “发到多个队列”是成立的
  - “单 worker 同时消费多个队列”不成立
- 如果你需要这两件事同时成立，请看 `RedisStreamBroker` + `additional_streams`

**正确做法**:
- 同一组同构 worker 可以共享一个 `queue_name`
- 不同服务、不同教程案例、不同职责边界的 worker 不要长期共享同一个队列
- 单 broker 示例统一使用 `TASKIQ_QUEUE_NAME`
- 多 broker 示例统一使用 `TASKIQ_QUEUE_NAME_<BROKER_NAME>`
- 模板层通过 `TaskiqConfig.queue_name` / `TASKIQ_QUEUE_NAME` 显式指定逻辑队列

```python
# ✅ 单 broker：显式队列
broker = ListQueueBroker(
    url="redis://default:123456@localhost:6379/0",
    queue_name=os.getenv("TASKIQ_QUEUE_NAME", "order-service:default"),
)
```

```python
# ✅ 多 broker：按职责拆队列
default_broker = ListQueueBroker(url=..., queue_name="orders:default")
high_priority_broker = ListQueueBroker(url=..., queue_name="orders:high")
```

**排查手段**:
- 看当前 broker 的 `queue_name`
- 看后台是否还有旧 worker 在跑
- 看 worker 日志里是否出现：

```text
task "xxx" is not found. Maybe you forgot to import it?
```

**边界说明**:
- 这个问题属于 `ListQueueBroker`
- `PubSubBroker` 是广播模式，不会“只被一个 worker 抢到”，但它也不是任务队列隔离方案
- 如果你本来就是要做“同类 worker 横向扩容”，共享同一个 `queue_name` 是正确用法

## 3. 在 `async def` 里塞同步阻塞代码

**现象**: Worker 吞吐量极低，任务排队严重。

**原因**: 在 async 任务中调用了同步阻塞操作，例如 `time.sleep()`、同步 HTTP 请求、同步数据库查询。

```python
# ❌ 错误：同步阻塞
@broker.task
async def bad_task():
    time.sleep(10)
    requests.get("https://api.example.com")

# ✅ 正确：使用 async 库
@broker.task
async def good_task():
    await asyncio.sleep(10)
    async with httpx.AsyncClient() as client:
        await client.get("https://api.example.com")

# ✅ 另一种边界：sync def 默认走 threadpool
@broker.task
def sync_task():
    time.sleep(10)
```

**边界说明**:
- `async def` 中的同步阻塞会卡住事件循环
- `sync def` 默认走 threadpool，不会卡事件循环，但会占住线程
- CPU 密集型同步任务建议改用 process pool

## 4. 依赖注入循环引用

**现象**: Worker 启动时报错 `RecursionError` 或依赖解析超时。

**原因**: 依赖 A 依赖 B，B 又依赖 A，形成循环。

```python
# ❌ 错误：循环依赖
async def get_a(b=TaskiqDepends(get_b)):
    return {"a": True, "b": b}

async def get_b(a=TaskiqDepends(get_a)):
    return {"b": True, "a": a}

# ✅ 正确：提取公共依赖
async def get_config():
    return {"shared": True}

async def get_a(config=TaskiqDepends(get_config)):
    return {"a": True, **config}

async def get_b(config=TaskiqDepends(get_config)):
    return {"b": True, **config}
```

## 5. Result Backend 结果不过期

**现象**: Redis 内存持续增长，最终 OOM。

**原因**: 配置了 `result_backend` 但未设置 `result_ex_time`，任务结果永不过期。

```python
# ❌ 错误：未设置过期时间
backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
)

# ✅ 正确：设置过期时间
backend = RedisAsyncResultBackend(
    redis_url="redis://default:123456@localhost:6379/1",
    result_ex_time=3600,
)
```

**排查**:
- `redis-cli -a 123456 -n 1 DBSIZE`

## 6. `PubSubBroker` 和 `ListQueueBroker` 混用

**现象**: 同一条消息被多个 worker 重复处理，或者你期待广播却只看到一个消费者。

**原因**: 选错 broker 模型。

```python
# ❌ 错误：用 PubSub 做任务队列
from taskiq_redis import PubSubBroker
broker = PubSubBroker(url=..., queue_name="broadcast")

# ✅ 正确：任务队列用 ListQueueBroker
from taskiq_redis import ListQueueBroker
broker = ListQueueBroker(url=..., queue_name="orders:default")
```

**选型原则**:
- 任务处理（每条消息只处理一次）→ `ListQueueBroker`
- 事件通知（所有订阅者都收到）→ `PubSubBroker`

## 7. 误解 `with_result_backend()` / `with_middlewares()` 的行为

**现象**:
- 文档或代码里把它当成“返回新对象”
- 结果虽然通常还能跑，但团队成员对对象身份理解错误，容易推导出错误结论

**真实行为**:
- TaskIQ 当前实现里，`with_result_backend()` / `with_middlewares()` 都是原地更新当前 broker，并返回 `self`

```python
broker = ListQueueBroker(url=..., queue_name="orders:default")
same_broker = broker.with_result_backend(backend)

assert broker is same_broker
```

**推荐写法**:
- 继续允许重新赋值，因为可读性更清楚
- 但不要再把它解释成“返回全新 broker”

```python
# ✅ 推荐：为了表达“绑定完成后的 broker”，显式重新赋值
broker = ListQueueBroker(url=..., queue_name="orders:default")
broker = broker.with_result_backend(backend)
```

## 8. 任务参数不可序列化

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

## 9. Worker 和 Client 的 broker 对象不一致

**现象**:
- 客户端发送的任务 worker 收不到
- worker 报 unknown task 或 `task "... " is not found`

**原因**:
- worker 和 client 用的不是同一个 broker 模块
- 或者虽然是同一个模块，但 `queue_name` / `task_name` 配置不一致

```bash
# Worker 使用的 broker
taskiq worker myapp.broker:broker
```

```python
# Client 也必须 import 同一个 broker 对象
from myapp.broker import broker
```

## 10. `on_error` 中重新发送导致无限循环或错误结果

**现象**:
- 任务不断重试，永不停止，Redis 队列堆积
- 或者 `wait_result()` 提前返回中间失败
- 或者较晚写回的旧失败结果覆盖最终成功结果

**原因**:
- 重试中间件没有设置最大重试次数，或者重试计数器没有正确递增
- 如果沿用同一个 `task_id` 重试，但没有跳过本次中间失败的结果保存，TaskIQ 仍会把这次失败写进 result backend

```python
# ❌ 错误：无限重试
async def on_error(self, message, result, error):
    await self.broker.kick(message)

# ❌ 也不完整：虽然限制了次数，但中间失败仍会被保存
async def on_error(self, message, result, error):
    retry_count = int(message.labels.get("_retry_count", "0"))
    max_retries = int(message.labels.get("max_retries", "3"))
    if retry_count < max_retries:
        message.labels["_retry_count"] = str(retry_count + 1)
        serialized = self.broker.formatter.dumps(message)
        await self.broker.kick(serialized)
    else:
        logger.error("重试耗尽: %s", error)

# ✅ 正确：限制重试次数，并跳过这次中间失败的结果保存
from taskiq.exceptions import NoResultError

async def on_error(self, message, result, error):
    retry_count = int(message.labels.get("_retry_count", "0"))
    max_retries = int(message.labels.get("max_retries", "3"))
    if retry_count < max_retries:
        message.labels["_retry_count"] = str(retry_count + 1)
        serialized = self.broker.formatter.dumps(message)
        await self.broker.kick(serialized)
        result.error = NoResultError()   # 跳过本次中间失败的结果保存
    else:
        logger.error("重试耗尽: %s", error)
```

补充:

- `ListQueueBroker.kick()` 的语义是“重新排队”，不是“立即重试”
- 如果你需要更可靠的 pending / ack / reclaim 语义，请优先评估 `RedisStreamBroker`

## 11. 忘记在 FastAPI lifespan 中管理 broker

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

## 12. `wait_result()` 不设置 timeout

**现象**: 客户端永久挂起，等待一个永远不会完成的任务。

**原因**: `wait_result()` 默认无超时；当 worker 崩溃、队列冲突消费、任务丢失时，调用方会一直等下去。

```python
# ❌ 错误：无超时
result = await handle.wait_result()

# ✅ 正确：始终设置 timeout
result = await handle.wait_result(timeout=30)
```

`wait_result()` 本身是异步等待，不是同步阻塞；真正的问题是“不设 timeout 会无限挂起”。

## 13. 在模块顶层 import 重量级资源

**现象**: Worker 启动慢，内存占用高。

**原因**: 在模块顶层 import 了 ML 模型、大型数据集等。

```python
# ❌ 错误：顶层 import 重量级模块
import tensorflow as tf
model = tf.keras.models.load_model("big_model.h5")

# ✅ 正确：在 startup 事件中加载，通过 State 共享
@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState):
    import tensorflow as tf
    state.model = tf.keras.models.load_model("big_model.h5")
```
