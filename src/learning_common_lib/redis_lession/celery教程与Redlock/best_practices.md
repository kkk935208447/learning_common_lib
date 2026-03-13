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
- 设置 `task_soft_time_limit` 和 `task_time_limit`，防止任务永远挂起

## 2. 任务定义

- 使用 `bind=True`，获取 `self` 访问 `self.request`、`self.retry()`
- 显式指定 `name=` 参数，防止重构移动文件后任务名变化导致路由失败
  ```python
  @app.task(bind=True, name="order.process")
  def process_order(self, order_id: int) -> dict: ...
  ```
- 任务参数只传 JSON 可序列化类型（str/int/float/list/dict/None/bool）
- 不要传 ORM 对象，传 ID 让 worker 侧重新查询（避免序列化问题 + 数据一致性）
- 任务函数保持幂等：同一参数多次执行结果一致

## 3. 任务调用

- 优先用 `apply_async()` 而非 `delay()`，前者支持所有参数
- 异步发布侧用 `asyncio.to_thread(task.delay, ...)` 包装，避免阻塞事件循环
- 设置 `expires` 防止过期消息堆积
- 不要在任务内部同步调用另一个任务的 `.get()`（死锁风险）

## 4. 错误处理

- 区分可重试错误和致命错误
  ```python
  # 可重试：网络超时、限流、外部服务暂时不可用
  # 致命：参数校验失败、业务逻辑错误、权限不足
  ```
- 使用指数退避重试：`retry_backoff=True, retry_backoff_max=600`
- 设置合理的 `max_retries`（推荐 3-5 次），避免无限重试
- `acks_late=True` + `reject_on_worker_lost=True`：worker 崩溃时任务重新入队

## 5. 队列与路由

- 按任务类型分队列：CPU 密集型、IO 密集型、快速任务分开
- 不同队列启动不同 concurrency 的 worker
  ```bash
  celery -A app worker -Q cpu_heavy --concurrency=2
  celery -A app worker -Q io_tasks --concurrency=20
  ```
- `worker_prefetch_multiplier=1`：一次只预取一个任务，配合 `acks_late` 实现公平调度

## 6. 定时任务

- 生产环境只运行一个 Beat 进程（多个会导致重复调度）
- 使用 `django-celery-beat` 或自定义 DatabaseScheduler 实现动态调度
- crontab 表达式注意时区：`timezone = "Asia/Shanghai"`

## 7. 工作流

- chain 中某个任务失败，后续任务不会执行（错误传播）
- chord 的 callback 只在所有 header 任务成功后才执行
- 避免超长 chain（>10 步），改用状态机或 saga 模式
- group 中的任务数量不要过大（>1000），考虑用 chunks 分批

## 8. 监控

- 生产环境部署 Flower：`celery -A app flower --port=5555`
- 开启 `worker_send_task_events=True` 获取实时事件
- 利用 task signals 做结构化日志、指标采集
- 监控队列长度，设置告警阈值

## 9. 分布式锁

- 锁超时（timeout）必须大于任务最大执行时间，否则锁提前释放导致并发问题
- 使用 redis-py 内置 `Lock`（基于 Lua 脚本，原子性有保证）
- 锁名使用业务语义：`lock:order:{order_id}`，不要用 UUID
- 获取锁失败时快速失败（抛异常），不要无限等待
- 释放锁时校验 owner token（redis-py Lock 默认行为）

## 10. FastAPI 集成

- 使用 lifespan 管理 Celery app 和 Redis 连接的生命周期
- 任务发布用 `asyncio.to_thread()` 包装，不阻塞 ASGI 事件循环
- 提供 `/tasks/{task_id}/status` 轮询端点，返回标准化状态
- 考虑 WebSocket 推送替代轮询（高频场景）

## 11. Worker 部署

- 使用 supervisor 或 systemd 管理 worker 进程，确保崩溃自动重启
  ```ini
  # /etc/supervisor/conf.d/celery_worker.conf
  [program:celery_worker]
  command=celery -A myapp worker -l info -c 4
  autostart=true
  autorestart=true
  stopwaitsecs=600
  ```
- 日志配置：`--logfile=/var/log/celery/worker.log --loglevel=info`
- 多队列部署：每个队列一个 worker 组，独立扩缩容
- 代码更新后必须重启 worker（worker 不会自动加载新代码）

## 12. Redis Broker 调优

- 设置 `maxmemory` 和 `maxmemory-policy allkeys-lru`，防止 OOM
- Broker 和 Backend 使用不同 Redis db（或不同实例），隔离故障域
- 开启 RDB 或 AOF 持久化，防止 broker 重启丢消息
- 监控 `info memory` 和队列长度，设置告警
