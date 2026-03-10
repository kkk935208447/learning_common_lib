# 架构映射（architecture_map）

本文档说明教程中的知识点如何映射到真实企业异步系统的各个架构层。

## 企业级异步系统的典型分层

```text
┌─────────────────────────────────────────────┐
│              入口层 (Entry)                   │
│  asyncio.run / 框架启动 / 信号处理            │
├─────────────────────────────────────────────┤
│            调用层 (Invocation)                │
│  发起异步调用、组织并发任务                     │
├─────────────────────────────────────────────┤
│          并发控制层 (Concurrency Control)      │
│  Semaphore / 有界队列 / Worker Pool           │
├─────────────────────────────────────────────┤
│           超时层 (Timeout)                    │
│  单调用超时 / 批量超时 / 全链路超时             │
├─────────────────────────────────────────────┤
│           重试层 (Retry)                      │
│  指数退避 / 可重试异常白名单 / jitter          │
├─────────────────────────────────────────────┤
│          取消与清理层 (Cancellation)           │
│  CancelledError 处理 / 资源释放 / 取消传播     │
├─────────────────────────────────────────────┤
│        后台任务层 (Background Tasks)           │
│  任务注册 / 异常回收 / 生命周期管理             │
├─────────────────────────────────────────────┤
│         阻塞桥接层 (Blocking Bridge)          │
│  to_thread / 进程池 / 同步库适配               │
├─────────────────────────────────────────────┤
│          关闭层 (Shutdown)                    │
│  信号接收 / 停止接收 / 取消任务 / 资源释放      │
└─────────────────────────────────────────────┘
```

## 知识点 → 架构层 → 教程文件 → 模板

| 架构层 | 解决什么问题 | 教程示例 | 企业模板 |
|--------|-------------|---------|---------|
| 入口层 | 程序启动与事件循环 | `01_basics/01_run_coroutine.py` | — |
| 调用层 | 组织并发任务 | `01_basics/02_sequential_vs_gather.py`、`02_structured_concurrency/` | `executor.py` |
| 并发控制层 | 防止资源耗尽 | `05_backpressure/` | `executor.py`（内置 Semaphore） |
| 超时层 | 防止无限等待 | `03_timeout/` | `executor.py`（内置 per-task timeout） |
| 重试层 | 应对瞬时故障 | `06_retry/` | `retry.py` |
| 取消与清理层 | 资源不泄漏 | `04_cancellation/` | 各模板内置取消处理 |
| 后台任务层 | 长生命周期任务管理 | `08_service_lifecycle/01_background_tasks.py` | `background_tasks.py` |
| 阻塞桥接层 | 接入同步代码 | `07_blocking_bridge/` | — |
| 关闭层 | 有序退出 | `08_service_lifecycle/02_graceful_shutdown.py` | `shutdown.py` |

## 一个典型的企业级异步调用链

以"批量调用外部 API 并汇总结果"为例：

```text
asyncio.run(main)                          # 入口层
  └─ AsyncExecutor(concurrency=10, timeout=5)  # 并发控制层 + 超时层
       └─ retry_with_backoff(call_api)         # 重试层
            └─ async with asyncio.timeout(5):  # 超时层（单调用）
                 └─ await http_client.get(url) # 实际 I/O
```

关闭时：

```text
signal(SIGTERM)                            # 关闭层
  └─ shutdown_event.set()
       └─ cancel all tasks                 # 取消与清理层
            └─ await cleanup()             # 资源释放
                 └─ close connections       # 阻塞桥接层（如有）
```

## 从教程到生产的演进路径

1. 先用示例理解每个概念的边界和行为
2. 阅读 `templates/` 了解如何将概念封装为可复用组件
3. 在实际项目中按架构层组合模板
4. 根据业务需求扩展：添加熔断、降级、链路追踪、指标采集等

模板只覆盖最基础的骨架，不覆盖：
- 熔断器（circuit breaker）
- 服务降级（fallback）
- 分布式追踪（tracing）
- 指标采集（metrics）

这些属于更上层的基础设施，通常由框架或中间件提供。
