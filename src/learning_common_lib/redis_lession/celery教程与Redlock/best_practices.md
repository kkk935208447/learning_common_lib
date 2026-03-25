# 最佳实践 (Best Practices)

## 1. 配置

- 序列化强制 JSON，禁用 pickle（安全 + 跨语言兼容）
  ```python
  task_serializer = "json"
  result_serializer = "json"
  accept_content = ["json"]
  ```
- broker 和 backend 使用不同 Redis db（db=0 / db=1），避免 key 冲突
- 连接串从环境变量读取，不硬编码密码
- 设置 `result_expires`（推荐 3600s），防止 Redis 内存无限增长
- `task_acks_late` 与 `broker_transport_options` 分开理解：前者是 ack 时机，后者是 broker 传输层行为
- Redis broker 可按需设置 `broker_transport_options = {"visibility_timeout": 3600}`
- `visibility_timeout` 不是 worker 生死探测器；它只是 Redis transport 判断“多久后允许再次投递”的窗口
- 设置 `task_soft_time_limit` 和 `task_time_limit`，防止任务永远挂起

## 2. 任务定义

- 使用 `bind=True`，获取 `self` 访问 `self.request`、`self.retry()`
- 优先把任务放在稳定的绝对包路径下，使用 Celery 自动生成的 `module.function` 任务名
- 只有在“跨服务固定契约”或“兼容历史名字”时，才显式指定 `name=`
  ```python
  # 推荐：稳定包路径 + 自动命名
  # myproj/orders/tasks.py -> myproj.orders.tasks.process_order
  ```
- `Celery("myproj")` 的 app 名用项目包名，不要用 `worker`、`demo`、`add_test` 这类临时名称
- 任务参数只传 JSON 可序列化类型（str/int/float/list/dict/None/bool）
- 不要传 ORM 对象，传 ID 让 worker 侧重新查询（避免序列化问题 + 数据一致性）
- 任务函数保持幂等：同一参数多次执行结果一致

## 3. 任务调用

- 优先用 `apply_async()` 而非 `delay()`，前者支持所有参数
- 异步发布侧用 `asyncio.to_thread(task.delay, ...)` 包装，避免阻塞事件循环
- 在 async producer 中，`AsyncResult.state/ready/successful/failed/forget()` 也应通过 `asyncio.to_thread(...)` 调用，因为它们同样可能触发同步 backend IO
- 设置 `expires` 防止过期消息堆积
- 不要在任务内部同步调用另一个任务的 `.get()`（死锁风险）

## 4. Async Worker 与 Async Task

- 先区分 producer async 和 worker async：`asyncio.to_thread(task.delay, ...)` 只是在 async Web/RPC 场景下安全发布任务
- `prefork` 仍是默认基线，优先给 CPU 任务、阻塞式 SDK、传统同步代码
- `gevent` 是 Celery 官方 greenlet 中间态：适合 cooperative IO，但 task 依然是 `sync def`
- `async def task` 只适合真正使用异步库的 IO 场景，例如 `httpx.AsyncClient`、异步数据库驱动、异步 Redis 客户端
- Celery 的 producer API、`AsyncResult`、`python-redis-lock` 在这个教程里都仍是同步客户端；async 场景只是通过 `asyncio.to_thread(...)` 包装这些边界
- 迁移期可以先在同步 task 中使用 `asyncio.run(...)` 桥接协程，但大量 async IO 更适合拆独立 aio worker
- `celery-aio-pool` 适合放到专门队列，例如 `aio_jobs`；不要让同步、greenlet、aio 任务无界混跑
- CPU 密集型任务仍优先 `prefork`，不要因为风格统一而强行改成 async task

## 5. 错误处理

- 区分可重试错误和致命错误
  ```python
  # 可重试：网络超时、限流、外部服务暂时不可用
  # 致命：参数校验失败、业务逻辑错误、权限不足
  ```
- 使用指数退避重试：`retry_backoff=True, retry_backoff_max=600`
- 设置合理的 `max_retries`（推荐 3-5 次），避免无限重试
- `acks_late=True` + `reject_on_worker_lost=True`：worker 崩溃时更容易触发重新投递，但这依然是 at-least-once，不是 exactly-once
- 重复投递是 broker 语义，副作用去重仍然要靠业务幂等

## 6. 队列与路由

- 按任务类型分队列：CPU 密集型、IO 密集型、快速任务分开
- 不同队列启动不同 concurrency 的 worker
  ```bash
  celery -A myproj.celery_app:app worker -Q cpu_heavy --concurrency=2
  celery -A myproj.celery_app:app worker -Q io_tasks --concurrency=20
  ```
- async task 建议独立部署 aio worker
  ```bash
  export CELERY_CUSTOM_WORKER_POOL='celery_aio_pool.pool:AsyncIOPool'
  celery -A myproj.celery_app:app worker -P custom -Q aio_jobs --concurrency=50
  ```
- cooperative IO 任务可以放到官方 greenlet worker
  ```bash
  celery -A myproj.celery_app:app worker -P gevent -Q greenlet_jobs --concurrency=100
  ```
- `worker_prefetch_multiplier=1`：一次只预取一个任务，配合 `acks_late` 实现公平调度

## 7. 定时任务

- 生产环境只运行一个 Beat 进程（多个会导致重复调度）
- 使用 `django-celery-beat` 或自定义 DatabaseScheduler 实现动态调度
- crontab 表达式注意时区：`timezone = "Asia/Shanghai"`

## 8. 工作流

- chain 中某个任务失败，后续任务不会执行（错误传播）
- chord 的 callback 只在所有 header 任务成功后才执行
- 避免超长 chain（>10 步），改用状态机或 saga 模式
- group 中的任务数量不要过大（>1000），考虑用 chunks 分批

## 9. 监控

- 生产环境部署 Flower：`celery -A myproj.celery_app:app flower --port=5555`
- 开启 `worker_send_task_events=True` 获取实时事件
- 利用 task signals 做结构化日志、指标采集
- 监控队列长度，设置告警阈值

## 10. 分布式锁

- 锁超时（timeout）必须大于任务最大执行时间，否则锁提前释放导致并发问题
- 教程基础篇可先用 redis-py 内置 `Lock` 理解原理
- 纯异步项目优先使用 `templates/distributed_lock_aio.py`，它是原生 `redis.asyncio` 看门狗实现
- `templates/distributed_lock.py` 继续保留 `python-redis-lock` 同步兼容路径
- 优先用 `async with async_distributed_lock(...)` / `with distributed_lock(...)` 明确标出临界区，装饰器只在重复样板很多时再上
- 锁名使用业务语义：`lock:order:{order_id}`，不要用 UUID
- 获取锁失败时快速失败（抛异常），不要无限等待
- 长任务不要只依赖固定 TTL；要先演示“固定 TTL 的失败态”，再引入看门狗续期
- 教学上优先打印 TTL 时间轴，再引入封装；否则很容易把“续期”理解成黑盒魔法
- 看门狗解决的是“长任务期间持续续期”，不是把所有锁问题都自动消灭
- 分布式锁解决的是“执行互斥”，不是“消息恢复”或“副作用幂等”
- 锁释放阶段如果出现“锁已过期 / owner 不匹配 / Redis 异常”，业务层可以不二次抛错，但必须保留结构化日志

## 11. FastAPI 集成

- 使用 lifespan 管理 Celery app 和 Redis 连接的生命周期
- 接受 FastAPI 发布侧继续用 `asyncio.to_thread()` 包装；这只是 Celery 客户端兼容层，不代表 worker 没有 async 化
- 提供 `/tasks/{task_id}/status` 轮询端点，返回标准化状态
- 考虑 WebSocket 推送替代轮询（高频场景）

## 12. Worker 部署

- 使用 supervisor 或 systemd 管理 worker 进程，确保崩溃自动重启
  ```ini
  # /etc/supervisor/conf.d/celery_worker.conf
  [program:celery_worker]
  command=celery -A myproj.celery_app:app worker -l info -P custom -c 20 -Q aio_jobs
  autostart=true
  autorestart=true
  stopwaitsecs=600
  ```
- 统一提供单一 app 入口，例如 `myproj/celery_app.py`，避免 worker / beat / Flower 分别指向不同模块
- 日志配置：`--logfile=/var/log/celery/worker.log --loglevel=info`
- 多队列部署：每个队列一个 worker 组，独立扩缩容
- 同步队列、greenlet 队列、aio 队列分开部署，避免 pool 模型互相牵制
- 代码更新后必须重启 worker（worker 不会自动加载新代码）

## 13. Redis Broker 调优

- 设置 `maxmemory` 和 `maxmemory-policy allkeys-lru`，防止 OOM
- Broker 和 Backend 使用不同 Redis db（或不同实例），隔离故障域
- 开启 RDB 或 AOF 持久化，防止 broker 重启丢消息
- 监控 `info memory` 和队列长度，设置告警
