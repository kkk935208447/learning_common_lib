# 企业级异步模板

这些模板是从教程示例中提炼的可复用骨架，适合直接集成到生产项目中。

## 模板清单

| 模板 | 解决什么 | 不解决什么 |
|------|---------|-----------|
| executor.py | 并发上限 + 超时 + 结果汇总 | 任务间依赖、编排 |
| retry.py | 指数退避重试 + 可重试异常白名单 | 熔断、降级 |
| background_tasks.py | 后台任务注册 + 异常回收 + 关闭回收 | 任务调度、定时任务 |
| shutdown.py | 跨平台信号处理 + 有序清理 | 进程管理、容器编排 |
| result_types.py | 统一结果结构 | 业务领域模型 |

## 使用方式

templates/ 是一个 Python 包（含 `__init__.py`），从 asyncio教程/ 目录可直接导入：

```bash
uv run python -c "from templates import AsyncExecutor, TaskResult; print('ok')"
```

也可以单独导入某个模块：

```bash
uv run python -c "from templates.retry import retry_with_backoff; print('ok')"
```

单独运行某个模板的 demo：

```bash
uv run python templates/executor.py
```

## 重要提醒
这些模板是教学骨架，不是成熟框架。生产使用时请根据实际需求调整。
