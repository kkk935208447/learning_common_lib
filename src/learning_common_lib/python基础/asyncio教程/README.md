# asyncio 教程（偏生产级）

这份教程与当前项目代码独立，目标是提供一套可直接运行、可逐步学习、并适合企业级项目参考的 `asyncio` 学习资料。

适用对象：

- 想系统掌握 Python 异步编程的开发者
- 想写出更稳健、更可维护 asyncio 代码的工程师
- 想在服务端、爬虫、Agent、数据处理、API 聚合等场景使用 asyncio 的同学

---

## 环境要求

- Python 3.11+（TaskGroup、asyncio.timeout 等现代 API 需要 3.11）。当前仓库 uv 环境约束为 `>=3.11,<3.12`，示例语义上兼容 3.12/3.13，但未在这些版本上做过验证
- 无第三方依赖，所有示例仅使用标准库
- Windows 用户注意：部分信号处理示例（如 `add_signal_handler`）在 Windows 下行为不同，示例中已提供 fallback 方案
- IDE 用户注意：某些 IDE 的内置终端可能不支持信号处理，建议在系统终端中运行 `08_service_lifecycle` 相关示例

---

## 目录结构

```text
asyncio教程/
├── README.md                 ← 你在这里
├── roadmap.md                ← 学习路线与排序理由
├── architecture_map.md       ← 知识点 → 企业架构角色映射
├── best_practices.md         ← 推荐做法
├── pitfalls.md               ← 反模式与错误边界
├── examples/
│   ├── 01_basics/
│   │   ├── 01_run_coroutine.py
│   │   ├── 02_sequential_vs_gather.py
│   │   └── 03_as_completed.py
│   ├── 02_structured_concurrency/
│   │   ├── 01_taskgroup_success.py
│   │   └── 02_taskgroup_fail_fast.py
│   ├── 03_timeout/
│   │   ├── 01_single_call_timeout.py
│   │   └── 02_batch_timeout.py
│   ├── 04_cancellation/
│   │   ├── 01_cancel_cleanup.py
│   │   └── 02_cancel_propagation.py
│   ├── 05_backpressure/
│   │   ├── 01_semaphore_limit.py
│   │   ├── 02_bounded_queue.py
│   │   └── 03_worker_pool.py
│   ├── 06_retry/
│   │   ├── 01_retry_with_backoff.py
│   │   └── 02_retry_boundary.py
│   ├── 07_blocking_bridge/
│   │   ├── 01_to_thread.py
│   │   └── 02_process_pool.py
│   └── 08_service_lifecycle/
│       ├── 01_background_tasks.py
│       └── 02_graceful_shutdown.py
├── templates/
│   ├── README.md
│   ├── executor.py
│   ├── retry.py
│   ├── background_tasks.py
│   ├── shutdown.py
│   └── result_types.py
└── smoke/
    └── run_all_examples.py
```

---

## 如何运行示例

先进入教程目录：

```bash
cd src/learning_common_lib/python基础/asyncio教程
```

然后运行任意示例：

```bash
uv run python examples/01_basics/01_run_coroutine.py
```

或者从仓库根目录直接运行（需要 shell 支持中文路径）：

```bash
uv run python "src/learning_common_lib/python基础/asyncio教程/examples/01_basics/01_run_coroutine.py"
```

运行 smoke 测试验证所有示例：

```bash
uv run python smoke/run_all_examples.py
```

---

## 学习路线概览

详细的学习顺序和排序理由见 [roadmap.md](roadmap.md)。

| 阶段 | 主题 | 目录 | 你会学到 |
|------|------|------|---------|
| 1 | 核心模型 | `01_basics/` | 协程、gather、as_completed |
| 2 | 结构化并发 | `02_structured_concurrency/` | TaskGroup 成功路径与失败联动取消 |
| 3 | 超时控制 | `03_timeout/` | 单调用超时、批量超时 |
| 4 | 取消与清理 | `04_cancellation/` | 取消处理、取消传播 |
| 5 | 背压与并发控制 | `05_backpressure/` | Semaphore、有界队列、worker pool |
| 6 | 重试策略 | `06_retry/` | 指数退避、可重试 vs 不可重试错误 |
| 7 | 阻塞桥接 | `07_blocking_bridge/` | to_thread、进程池 |
| 8 | 服务生命周期 | `08_service_lifecycle/` | 后台任务管理、优雅关闭 |

学完示例后，阅读 `templates/` 了解如何将这些知识点封装为企业级可复用组件。

---

## 核心原则

1. **不要把阻塞代码直接写进协程** — `time.sleep()` 会卡死事件循环，用 `asyncio.to_thread()` 或进程池
2. **所有外部调用都加超时** — 不加超时，高并发下任务会无限堆积
3. **所有并发都限制上限** — 用 Semaphore、有界队列或连接池，不要一次性启动几千个请求
4. **不要创建后台任务后不管理** — 至少保留引用、记录日志、处理异常、退出时取消
5. **优先使用现代 API** — `asyncio.run()`、`TaskGroup`、`asyncio.timeout()`、`asyncio.to_thread()`

---

## 文档说明

| 文档 | 内容 |
|------|------|
| [roadmap.md](roadmap.md) | 学习路线、排序理由、版本要求 |
| [architecture_map.md](architecture_map.md) | 教程知识点 → 企业架构层映射 |
| [best_practices.md](best_practices.md) | 推荐做法（怎么写好） |
| [pitfalls.md](pitfalls.md) | 反模式与错误边界（怎么写错） |
| [templates/README.md](templates/README.md) | 企业级模板使用说明 |

---

## 学完后你应该具备的能力

- 编写高并发 I/O 程序
- 使用 TaskGroup 管理并发任务，理解失败联动取消
- 为异步调用添加超时、重试、取消和限流
- 正确接入同步阻塞函数和 CPU 密集任务
- 管理后台任务生命周期
- 编写可优雅关闭的服务端异步代码

---

## 最后建议

学习 asyncio 时，不要只记 API，要建立这几个判断：

1. 这段代码是不是在等待外部资源？
2. 这段代码会不会阻塞事件循环？
3. 这个任务要不要限流？
4. 这个任务失败了怎么重试？
5. 这个任务卡死了多久超时？
6. 进程退出时要如何清理？

如果你能习惯这样思考，asyncio 才真正进入"工程使用"阶段。
