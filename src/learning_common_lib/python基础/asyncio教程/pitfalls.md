# asyncio 常见坑与反模式

这份文档只讲"什么会出错、为什么出错"。推荐做法见 [best_practices.md](best_practices.md)。

---

## 1. 调用协程函数但没有 await

```python
# 错误：返回的是协程对象，不是结果
x = foo()

# 正确
x = await foo()
```

Python 会发出 `RuntimeWarning: coroutine 'foo' was never awaited`，但很容易被忽略。

---

## 2. 以为 async def 就自动并发

```python
# 这是顺序执行，不是并发
await task1()
await task2()
```

两个 await 是串行的。并发需要 `TaskGroup` 或 `gather`。

---

## 3. 在协程里用 time.sleep()

```python
async def bad():
    time.sleep(2)  # 阻塞整个事件循环
```

所有其他协程在这 2 秒内都无法执行。用 `await asyncio.sleep()` 或 `asyncio.to_thread()`。

---

## 4. 在协程里跑 CPU 密集代码

```python
async def bad():
    total = sum(range(10**8))  # 没有任何 await 让出点
```

事件循环被卡住，其他协程饿死。CPU 密集任务用 `ProcessPoolExecutor`。

---

## 5. 创建任务后不保留引用

```python
asyncio.create_task(do_work())  # 引用丢失
```

后果：
- 任务可能被 GC 回收
- 异常无人处理（静默丢失）
- 程序退出时任务未完成
- 调试时找不到任务

---

## 6. 吞掉 CancelledError

```python
# 错误：破坏取消语义
try:
    await do_work()
except asyncio.CancelledError:
    pass  # 取消被吞掉，上层以为任务还在运行
```

处理完取消后必须重新 `raise`，否则 TaskGroup、timeout 等机制无法正常工作。

---

## 7. 用 gather 发起海量并发

```python
await asyncio.gather(*(call_api(i) for i in range(50000)))
```

后果：瞬间创建 5 万个协程，打爆文件描述符、连接池、下游服务。

---

## 8. 滥用 return_exceptions=True

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
# 然后直接用 results，不检查哪些是异常
```

`return_exceptions=True` 不是"消灭异常"，而是"把异常混进结果列表"。必须逐项检查 `isinstance(r, Exception)`。

---

## 9. 混用同步客户端与异步框架

在 FastAPI 异步接口里用 `requests.get()` 或同步数据库驱动：
- QPS 上不去
- 延迟不稳定
- 事件循环被阻塞

应优先换成异步客户端（httpx、aiohttp、asyncpg 等）。

---

## 10. 忽略资源关闭

异步程序中常见的资源泄漏：
- HTTP client 没关（连接池泄漏）
- 数据库连接没关
- WebSocket 没断开
- 队列消费者没停止
- 临时文件没删除

用 `async with` 管理资源生命周期。

---

## 11. 以为 asyncio 没有竞态条件

多个协程交错执行时，共享可变状态仍然会出问题：

```python
# 两个协程同时执行这段代码
balance = await get_balance()
await asyncio.sleep(0)  # 让出控制权
await set_balance(balance + 100)  # 可能覆盖另一个协程的写入
```

需要时用 `asyncio.Lock`。

---

## 12. 对不可恢复错误做重试

```python
# 错误：参数错误重试 3 次还是参数错误
retry_with_backoff(call_api, retry_exceptions=(Exception,))
```

应该区分：
- 可重试：网络超时、连接断开、5xx
- 不可重试：参数错误、权限不足、404、业务逻辑错误

---

## 13. 过度吞异常

```python
try:
    await work()
except Exception:
    pass  # 任务"悄悄失败"
```

至少要记录日志。对确实可忽略的错误，精确捕获具体异常类型。

---

## 14. 后台任务异常静默丢失

```python
task = asyncio.create_task(risky_work())
# 如果 risky_work 抛异常，没有任何地方会看到
```

必须通过 `done_callback` 或 `await task` 消费异常。见 `08_service_lifecycle/01_background_tasks.py`。

---

## 一句话总结

asyncio 真正难的地方不是 `await`，而是边界控制：什么会阻塞、什么需要限流、什么能重试、什么必须清理、什么异常不能吞。
