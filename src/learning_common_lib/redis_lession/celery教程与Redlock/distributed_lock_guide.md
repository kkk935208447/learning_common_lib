# 单 Redis 分布式锁原理与队列关系指南

配套文件：
- 基础示例：`examples/10_fastapi_integration/02_distributed_lock.py`
- 企业示例：`examples/10_fastapi_integration/03_watchdog_lock_with_celery.py`
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

### 为什么企业模板选 python-redis-lock

- Celery 长任务经常明显超过初始锁 TTL
- 固定 TTL 容易在任务未完成时提前失锁
- `python-redis-lock` 的 `auto_renewal=True` 能通过后台线程持续续期
- 因此教程基础篇用 `redis-py` 讲原理，企业模板直接用 `python-redis-lock`

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

### 第 6 章多队列设计

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

1. **分布式锁**: 教程基础篇用 `redis-py Lock` 讲原理，企业模板用 `python-redis-lock` 提供自动续期
2. **队列与锁**: 技术上正交，建议 db 隔离（broker=0, backend=1, lock=2）
3. **多队列**: 逻辑隔离满足大多数场景，物理隔离仅用于特殊需求
4. **生产建议**: 合理设置锁超时，监控 Redis 内存使用，定期清理过期数据
