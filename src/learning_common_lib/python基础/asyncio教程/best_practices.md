# asyncio 企业级最佳实践

这份文档只讲"推荐做法"。反模式和常见错误见 [pitfalls.md](pitfalls.md)。

---

## 1. 使用现代 API（Python 3.11+）

- 程序入口：`asyncio.run()`
- 并发管理：`asyncio.TaskGroup()`
- 超时控制：`asyncio.timeout()`
- 阻塞桥接：`asyncio.to_thread()`

不要在新代码里使用 `ensure_future()`、`loop.run_until_complete()` 等旧式 API。

---

## 2. 按场景选择并发模式

| 场景 | 推荐方式 | 示例 |
|------|---------|------|
| 全部完成再继续 | `TaskGroup` | `02_structured_concurrency/` |
| 先到先处理 | `as_completed` | `01_basics/03_as_completed.py` |
| 部分失败可接受 | `gather(return_exceptions=True)` + 逐项检查 | — |
| 需要限流 | Semaphore 或有界队列 | `05_backpressure/` |
| 生产者-消费者 | `asyncio.Queue(maxsize=N)` + worker pool | `05_backpressure/03_worker_pool.py` |

---

## 3. 超时分层设计

生产环境建议三层超时：

```python
# 单调用超时
async with asyncio.timeout(5):
    await call_api()

# 批量超时（包裹 TaskGroup）
async with asyncio.timeout(30):
    async with asyncio.TaskGroup() as tg:
        ...

# 全链路超时（在入口层设置）
async with asyncio.timeout(60):
    await process_request()
```

---

## 4. 并发控制三件套

生产环境的并发控制通常需要组合使用：

- `Semaphore`：控制同时执行的任务数
- 有界队列：控制待处理任务的积压量
- 连接池参数：控制底层资源占用

三者配合才能形成完整的背压链。

---

## 5. 任务生命周期管理

| 任务类型 | 推荐管理方式 |
|---------|-------------|
| 短生命周期并发 | `TaskGroup`（自动等待、自动取消） |
| 长生命周期后台任务 | 任务注册表 + done_callback + 日志 + shutdown 回收 |

后台任务至少要做到：
- 保留引用（防止被 GC）
- 命名（`create_task(coro, name="xxx")`）
- 异常回收（done_callback 检查 exception）
- 退出时取消

---

## 6. 取消处理的标准模式

```python
try:
    await do_something()
except asyncio.CancelledError:
    # 释放资源：关闭连接、flush 缓冲区、删除临时文件
    await cleanup()
    # 必须重新抛出，否则破坏取消语义
    raise
```

---

## 7. 重试策略设计

- 限制最大重试次数（通常 3-5 次）
- 使用指数退避（`base_delay * 2^attempt`）
- 加随机抖动（jitter），避免重试风暴
- 只重试可恢复错误（网络超时、连接断开、5xx）
- 不重试不可恢复错误（参数错误、权限不足、404）

---

## 8. 给任务命名并记录上下文

```python
task = asyncio.create_task(worker(), name="sync_user_profile")
```

日志中带上：task name、request id、业务 ID、批次 ID。异步程序排查问题比同步更难，可观测性是生命线。

---

## 9. 同步库桥接原则

- 轻量阻塞：`asyncio.to_thread(sync_func)`
- CPU 密集：`ProcessPoolExecutor`
- 高频调用：寻找原生异步实现，`to_thread` 只是过渡方案

---

## 10. 优雅关闭检查清单

1. 接收退出信号（SIGINT/SIGTERM）
2. 停止接收新任务
3. 取消正在执行的任务
4. 等待清理完成（设超时）
5. 关闭连接、flush 日志
6. 退出

---

## 11. 生产级代码自查清单

提交 asyncio 代码前，确认：

- [ ] 没有阻塞代码直接运行在协程里
- [ ] 外部调用都设置了超时
- [ ] 并发有上限控制
- [ ] 任务取消有清理逻辑
- [ ] 异常有日志记录
- [ ] 失败策略明确（整体失败 / 部分失败）
- [ ] 有资源清理逻辑
- [ ] 容易观察和排查问题
