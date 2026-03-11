# 学习路线（roadmap）

## 版本要求

- Python 3.11+（ExceptionGroup / `except*` 语法从 3.11 开始可用）
- 当前仓库 uv 环境约束为 `>=3.11,<3.12`，示例语义上兼容更高版本但未验证
- 如果你用 3.10 或更早版本，第六阶段的 ExceptionGroup 和 except* 示例无法运行
- 第八阶段需要安装 FastAPI 和 httpx：`uv add fastapi httpx`

## 学习顺序与理由

### 第一阶段：异常基础语法（01_basics/）

先理解 try/except/else/finally 的执行顺序和多异常匹配规则，这是后续所有内容的基础。

| 顺序 | 文件 | 学什么 | 为什么先学 |
|------|------|--------|-----------|
| 1 | `01_try_except_else_finally.py` | try 四件套执行顺序 | 最小可运行单元 |
| 2 | `02_multiple_except.py` | 多异常捕获与匹配顺序 | 基础语法完整覆盖 |

### 第二阶段：自定义异常体系（02_custom_exceptions/）

掌握如何设计带结构化字段的自定义异常，这是企业级异常架构的基石。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 3 | `01_basic_custom_exception.py` | 带结构化字段的自定义异常 | 企业级异常的基础 |
| 4 | `02_exception_hierarchy.py` | 项目级异常树设计 | 分层捕获的前提 |

### 第三阶段：异常链（03_exception_chain/）— 关键章节

这是大多数开发者写错的地方。理解 raise from 和异常链是写出可调试代码的关键。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 5 | `01_raise_from.py` | raise from 显式链 vs 隐式链 | 错误信息丢失的根源 |
| 6 | `02_anti_pattern_vs_correct.py` | 反模式 vs 正确做法对比 | 直击用户核心痛点 |

### 第四阶段：日志与 Traceback（04_traceback_logging/）

知道怎么抛异常之后，还要知道怎么记录异常。生产环境的可调试性取决于日志质量。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 7 | `01_traceback_format.py` | traceback 模块格式化 | 调试的基本功 |
| 8 | `02_logging_exc_info.py` | logging.exception + 结构化上下文 | 生产环境日志标准 |
| 9 | `03_json_structured_logging.py` | JSON 结构化日志 + request_id | 对接 ELK/Datadog |

### 第五阶段：上下文管理器中的异常（05_context_manager_errors/）

上下文管理器是 Python 资源管理的核心工具，理解它和异常的交互是写出异常安全代码的关键。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 10 | `01_suppress_and_handle.py` | contextlib.suppress + __exit__ | 异常处理的高级工具 |
| 11 | `02_cleanup_on_error.py` | 资源清理保证 | 异常安全的关键 |

### 第六阶段：ExceptionGroup（06_exception_group/）— Python 3.11+

现代 Python 的并发异常处理方式，TaskGroup 失败时会抛出 ExceptionGroup。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 12 | `01_exception_group_basics.py` | ExceptionGroup 创建与遍历 | 现代异常处理基础 |
| 13 | `02_except_star.py` | except* 语法 + TaskGroup | 并发异常处理 |

### 第七阶段：深层调用栈错误传播（07_deep_call_stack/）— 核心痛点

真实项目中调用栈往往有 5 层以上，异常在传播过程中信息丢失是最常见的问题。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 14 | `01_propagation_strategy.py` | 5 层调用栈传播策略 | 解决错误信息丢失 |
| 15 | `02_result_pattern.py` | Result 模式 | 异常的替代方案 |
| 16 | `03_async_propagation.py` | async 异常传播 + context manager 清理 | 异步场景对照 |

### 第八阶段：FastAPI 企业级错误架构（08_fastapi_error_architecture/）— 终极章节

放在最后，因为它综合了前面所有知识：自定义异常、异常链、日志、错误码、统一响应格式。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 17 | `01_layered_error_handling.py` | 完整 4 层架构 | 综合运用所有知识 |
| 18 | `02_error_code_registry.py` | 错误码注册表 + request_id | 企业级错误管理 |

### 第九阶段：异常测试（09_testing/）

知道怎么写异常之后，还要知道怎么测试异常。异常路径的测试覆盖率和正常路径同等重要。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 19 | `01_pytest_exception.py` | 异常捕获断言、字段断言、链断言、mock | 异常测试四件套 |

### 第十阶段：重试与退避（10_retry_and_idempotency/）

生产环境中，外部服务不可用和限流是常态。重试策略是异常处理的最后一环。

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 20 | `01_retry_with_backoff.py` | 指数退避、Retry-After、不可重试异常 | 异常处理闭环 |

## 学完示例后

阅读 `templates/` 目录，了解如何将这些知识点封装为企业级可复用组件。

阅读顺序建议：`error_base.py` → `error_registry.py` → `error_context.py` → `fastapi_error_handler.py`
