# 常见陷阱 (Pitfalls)

## 1. 序列化陷阱

### 传了不可序列化的对象
```python
# ❌ 错误：传 ORM 对象
@app.task
def process(user: User):  # User 是 SQLAlchemy 模型
    ...

# ✅ 正确：传 ID，worker 侧重新查询
@app.task
def process(user_id: int):
    user = db.query(User).get(user_id)
```

### datetime 不是 JSON 原生类型
```python
# ❌ 错误
task.delay(created_at=datetime.now())

# ✅ 正确
task.delay(created_at=datetime.now().isoformat())
```

## 2. 死锁陷阱

### 任务内同步等待另一个任务
```python
# ❌ 死锁：prefork 模式下所有 worker 都在等，没人执行
@app.task
def task_a():
    result = task_b.delay()
    return result.get()  # 阻塞等待 task_b，但 worker 池可能已满

# ✅ 正确：用 chain 编排
from celery import chain
chain(task_a.s(), task_b.s()).apply_async()
```

### .get() 无 timeout 导致永久阻塞
```python
# ❌ worker 未启动或任务卡住时永远等待
result = task.delay()
result.get()  # 永久阻塞

# ✅ 始终设置 timeout
result.get(timeout=30)  # 30 秒后抛出 TimeoutError
```

## 3. 重试陷阱

### 忘记设置 max_retries
```python
# ❌ 默认 max_retries=3，可能不够或太多
@app.task(bind=True)
def flaky_task(self):
    try:
        call_external_api()
    except TimeoutError:
        self.retry()  # 默认只重试 3 次

# ✅ 显式设置
@app.task(bind=True, max_retries=5)
def flaky_task(self):
    try:
        call_external_api()
    except TimeoutError:
        self.retry(countdown=60)  # 60 秒后重试
```

### autoretry 吞掉了不该重试的异常
```python
# ❌ 所有异常都重试，包括参数错误
@app.task(autoretry_for=(Exception,), max_retries=5)
def process(data):
    validate(data)  # ValueError 也会被重试

# ✅ 只重试特定异常
@app.task(autoretry_for=(ConnectionError, TimeoutError), max_retries=5)
def process(data):
    validate(data)  # ValueError 直接失败
    call_api(data)  # 网络错误才重试
```

## 4. 结果后端陷阱

### Redis 内存爆炸
```python
# ❌ 不设置过期时间，结果永远留在 Redis
app.conf.result_expires = None

# ✅ 设置合理过期时间
app.conf.result_expires = 3600  # 1 小时

# ✅ 不需要结果的任务标记 ignore_result
@app.task(ignore_result=True)
def send_email(to, subject, body): ...
```

### forget() 的时机
```python
# 获取结果后主动清理
result = task.delay()
value = result.get(timeout=10)
result.forget()  # 立即从 backend 删除
```

## 5. Beat 陷阱

### 多个 Beat 进程导致重复调度
```bash
# ❌ 启动了两个 beat
celery -A app beat &
celery -A app beat &  # 同一个任务会被调度两次

# ✅ 确保只有一个 beat 进程
# 使用 PID 文件或分布式锁保证单实例
celery -A app beat --pidfile=/var/run/celery/beat.pid
```

### 时区不一致
```python
# ❌ 服务器 UTC，配置里写的北京时间
app.conf.beat_schedule = {
    "daily-report": {
        "task": "report.generate",
        "schedule": crontab(hour=9, minute=0),  # 这是哪个时区的 9 点？
    }
}

# ✅ 显式设置时区
app.conf.timezone = "Asia/Shanghai"
```

## 6. 队列陷阱

### 任务发到了没人消费的队列
```python
# ❌ 配置了路由但没启动对应 worker
app.conf.task_routes = {"email.*": {"queue": "email"}}
# 只启动了 celery -A app worker（默认只消费 default 队列）

# ✅ 启动时指定队列
# celery -A app worker -Q default,email
```

### 优先级在 Redis 下的限制
```python
# Redis broker 的优先级是通过多个 list 模拟的（默认 0-9）
# 不如 RabbitMQ 的原生优先级精确
# 高并发下优先级可能不严格保证顺序
```

## 7. 连接陷阱

### broker 连接池耗尽
```python
# ❌ 每个请求都创建新的 Celery app
def handle_request():
    app = Celery(...)  # 每次新建，连接池无法复用
    task.delay()

# ✅ 全局单例
app = Celery(...)  # 模块级别创建一次
```

### Redis 密码包含特殊字符
```python
# ❌ 密码中有 @ 或 / 会破坏 URL 解析
broker_url = "redis://:p@ss/word@localhost:6379/0"

# ✅ URL 编码特殊字符
from urllib.parse import quote
password = quote("p@ss/word", safe="")
broker_url = f"redis://:{password}@localhost:6379/0"
```

## 8. 分布式锁陷阱

### 锁超时小于任务执行时间
```python
# ❌ 锁 10 秒超时，但任务可能跑 30 秒
with distributed_lock(redis, "order:123", timeout=10):
    process_order()  # 执行到一半锁就释放了，另一个 worker 拿到锁

# ✅ 锁超时 > 任务最大执行时间 + 余量
with distributed_lock(redis, "order:123", timeout=120):
    process_order()
```

### 异常时锁未释放
```python
# redis-py Lock 作为上下文管理器使用时会自动释放
# ❌ 但手动 acquire 后忘记 release
lock = redis.lock("my-lock")
lock.acquire()
do_something()  # 如果这里抛异常，锁不会释放
lock.release()

# ✅ 用上下文管理器
with redis.lock("my-lock", timeout=60):
    do_something()  # 异常时自动释放
```

### 误删他人的锁
```python
# redis-py Lock 内部使用 owner token（随机 UUID）
# release() 时会校验 token，不会误删其他进程持有的锁
# 但如果你手动 DEL key，就会误删
# ❌
redis.delete("my-lock")
# ✅
lock.release()  # 只释放自己持有的锁
```

## 9. Worker 启动顺序

### 先发任务后启动 worker
```python
# ❌ 任务发到 broker 但没有 worker 消费
task.delay()  # 消息堆积在 Redis 队列中
# 很久之后才启动 worker...

# ✅ 先启动 worker，再发任务
# 终端 1: celery -A app worker -l info
# 终端 2: python client.py
```

### .get() 无限阻塞
```python
# ❌ worker 未启动时 .get() 永远等待
result = task.delay()
result.get()  # 永远阻塞

# ✅ 始终设置 timeout
result.get(timeout=30)  # 30 秒后超时抛 TimeoutError
```

## 10. Worker 代码热更新

### 修改代码后忘记重启 worker
```python
# ❌ 修改了任务代码但 worker 还在运行旧版本
# worker 进程在启动时加载代码，之后不会自动更新

# ✅ 修改代码后重启 worker
# Ctrl+C 停止 worker → 重新启动
# 或使用 --autoreload（仅开发环境）
celery -A app worker -l info --autoreload
```
