# 单 Redis 分布式锁原理与队列关系指南

配套文件：
- 基础示例：`examples/11_fastapi_integration/02_distributed_lock.py`
- 最小看门狗示例：`examples/11_fastapi_integration/03_python_redis_lock_watchdog_minimal.py`
- 纯异步看门狗示例：`examples/11_fastapi_integration/03_python_redis_lock_watchdog_minimal2.py`
- 企业示例：`examples/11_fastapi_integration/04_watchdog_lock_with_celery.py`
- 纯异步模板：`templates/distributed_lock_aio.py`
- 企业模板：`templates/distributed_lock.py`

## Part 1: Redis 分布式锁原理

### 基本实现机制

Redis 分布式锁基于 `SET key value NX EX timeout` 原子操作实现：

```redis
SET lock:order:123 uuid-token NX EX 30
```

- **NX**: 仅当 key 不存在时设置（互斥性）
- **EX**: 设置过期时间（防死锁）
- **uuid-token**: 随机值，防止误删他人锁

### 释放锁的原子性

释放锁使用 Lua 脚本保证 check-owner-then-delete 原子性：

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

### redis-py Lock 类实现（基础篇）

redis-py 的 `Lock` 类内部实现：

1. **获取锁**: `SET key token NX EX timeout`
2. **释放锁**: 执行上述 Lua 脚本
3. **Owner Token**: 使用随机 UUID 防止误删
4. **阻塞获取**: 循环重试 + 指数退避

### 锁续期（Watchdog）

- **Java Redisson**: 有自动续期机制
- **redis-py**: 无自动续期，需合理设置 timeout
- **python-redis-lock**: 支持 `auto_renewal=True`，适合长任务
- **生产建议**: Celery 长任务优先使用带自动续期的锁封装

### 单 Redis 锁 vs 多节点 Redlock

#### 单 Redis 锁（本教程主线）
```python
import redis
client = redis.Redis(host="localhost", port=6379, db=2)
lock = client.lock("resource", timeout=30)
with lock:
    # 临界区
    do_work()
```

#### 多节点 Redlock 算法（扩展话题，不是本教程主线）
```python
from pottery import Redlock
masters = {redis1, redis2, redis3}
lock = Redlock(key="resource", masters=masters)
with lock:
    do_work()
```

### 为什么本教程主线不展开 Redlock

- 大多数业务真正需要的是“多服务实例之间互斥”，单 Redis 锁已经能覆盖
- 引入多节点 Redlock 会明显提高理解与运维复杂度
- 因此本教程主线聚焦单 Redis 分布式锁，把多节点方案作为扩展阅读

### 为什么现在保留两条企业模板路径

- Celery 长任务经常明显超过初始锁 TTL
- 固定 TTL 容易在任务未完成时提前失锁
- `distributed_lock_aio.py` 用 `redis.asyncio` + `asyncio` 看门狗解决纯异步路径的续期问题
- `distributed_lock.py` 继续保留 `python-redis-lock` 兼容实现，服务于仍在使用同步 Redis 客户端的项目
- 因此教程基础篇继续用 `redis-py Lock` 讲原理，企业模板则明确拆分成“纯异步主路径”和“同步兼容路径”
- 模板代码默认优先推荐 `distributed_lock_aio.py` 里的 `async_distributed_lock()`，同步代码再使用 `distributed_lock()` / `@with_lock`

### async-first 模板的准确边界

这里要把几个层次分开：

1. `custom aio pool + async def task`
   这是真正跑在 asyncio worker 执行层上的主线。
2. `task.delay()` / `AsyncResult.get()`
   这些接口本身仍然是同步客户端。
3. `distributed_lock_aio.py`
   这是原生 `redis.asyncio` 锁客户端，不需要 `to_thread(...)`。
4. `distributed_lock.py`
   这是同步 Redis / `python-redis-lock` 兼容路径。
5. `asyncio.to_thread(...)`
   它解决的是“在 async 调用侧不阻塞事件循环”，不是把底层客户端改造成原生 async。

所以在第 11 章里，正确理解应当是：

- worker 内部业务协程是 async 的
- 结果查询这些边界仍然是同步客户端，只是包装成了 async-friendly 调用
- 锁则同时提供原生 async 实现和同步兼容实现两条路径

### 教程里的对比主线

- `02_distributed_lock.py`: 先证明固定 TTL 在短任务里是够用的
- `02_distributed_lock.py`: 再证明同样的固定 TTL 放到长任务里会中途失锁
- `03_python_redis_lock_watchdog_minimal.py`: 先用最小脚本看懂 `python-redis-lock` 的 `auto_renewal` 会如何续期
- `03_python_redis_lock_watchdog_minimal2.py`: 再看纯异步看门狗如何在事件循环里续期
- `04_watchdog_lock_with_celery.py`: 最后在 Celery async worker 中对比 `auto_renewal=False/True`

### 最小可视化流程（建议先看）

先不要急着上装饰器，先用上下文管理器把锁边界看清楚：

1. 获取锁
2. 每秒读取 Redis 中锁 key 的 `PTTL`
3. 在固定时刻用第二个持有者 `acquire(blocking=False)` 探测能否抢锁
4. 任务结束后再探测一次，确认锁已释放

固定 TTL 和看门狗示例现在都采用这条观察路径，并且时间轴打印来自客户端直接读 Redis，不依赖 worker 控制台。
`@with_lock` 仍然保留在模板里，但应视为最后再上的语法糖，而不是主教学入口。

```python
async with async_distributed_lock(
    redis_client,
    "order:123",
    timeout=3,
    auto_renewal=True,
):
    for _ in range(5):
        ttl_ms = await redis_client.pttl("lock:order:123")
        print("ttl:", ttl_ms)
        await asyncio.sleep(1)
```

说明：

- 教程基础篇里，`redis-py Lock` 的 key 就是你传入的锁名，例如 `demo:order:123`
- `distributed_lock_aio.py` 与 `distributed_lock.py` 都把真实锁 key 统一成 `lock:{name}`
- 因此企业篇读取 TTL 时，要观察的是 `lock:{name}`

## Part 2: Celery 队列与分布式锁的关系

### 核心结论

**队列和锁是完全正交的概念，可以用同一个 Redis 实例，但应使用不同的 db。**

### 技术分析

#### 数据结构差异
- **Celery 队列**: 使用 Redis LIST（LPUSH/BRPOP）
  - Key 示例: `celery`, `email_queue`, `report_queue`
- **分布式锁**: 使用 Redis STRING（SET NX EX）
  - Key 示例: `lock:order:123`, `lock:user:456`

#### Key 命名空间
两者 key 命名空间天然不冲突，但共用 db 的风险：

1. **运维误操作**: `FLUSHDB` 会同时清除队列和锁
2. **内存淘汰**: `maxmemory` 策略可能误删锁 key 或队列消息
3. **监控排查**: key 混杂，难以区分问题来源

#### 推荐隔离策略
```
broker (队列):  redis://localhost:6379/0
backend (结果): redis://localhost:6379/1
lock (锁):     redis://localhost:6379/2
```

### 配置示例

```python
# Celery 配置
app.conf.update(
    broker_url="redis://:123456@localhost:6379/0",
    result_backend="redis://:123456@localhost:6379/1",
)

# 锁客户端
lock_client = redis.Redis(
    host="localhost", port=6379,
    password="123456", db=2
)
```

## Part 3: 教程中多队列使用的合理性

### 第 7 章多队列设计

```python
app.conf.task_queues = (
    Queue("email_queue"),
    Queue("report_queue"),
    Queue("notification_queue"),
)
```

### 设计合理性分析

#### ✅ 合理的生产实践
- **独立扩缩容**: 邮件队列可单独增加 worker
- **故障隔离**: 报表生成异常不影响邮件发送
- **资源配额**: 不同队列可设置不同的并发数和优先级

#### ✅ 逻辑隔离 vs 物理隔离
- **逻辑隔离**: 同一 Redis db 中的不同队列（教程做法）
- **物理隔离**: 不同 Redis 实例（特殊场景）

### 何时需要物理隔离

使用不同 Redis 实例的场景：

1. **跨业务线**: 订单系统 vs 用户系统
2. **不同 SLA**: 实时任务 vs 批处理任务
3. **不同安全域**: 内网 vs 外网任务
4. **地理分布**: 不同数据中心

### 配置示例

#### 逻辑隔离（推荐）
```python
# 所有队列在同一 Redis db=0
app.conf.task_routes = {
    'send_email': {'queue': 'email_queue'},
    'generate_report': {'queue': 'report_queue'},
}
```

#### 物理隔离（特殊场景）
```python
# 不同业务线使用不同 Redis
email_app = Celery(broker="redis://email-redis:6379/0")
report_app = Celery(broker="redis://report-redis:6379/0")
```

## 总结

1. **分布式锁**: 教程基础篇用 `redis-py Lock` 讲原理；企业模板同时提供纯异步看门狗实现和同步兼容实现
2. **队列与锁**: 技术上正交，建议 db 隔离（broker=0, backend=1, lock=2）
3. **多队列**: 逻辑隔离满足大多数场景，物理隔离仅用于特殊需求
4. **生产建议**: 合理设置锁超时，监控 Redis 内存使用，定期清理过期数据
