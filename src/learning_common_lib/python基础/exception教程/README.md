# Python 异常处理教程（偏生产级）

这份教程与当前项目代码独立，目标是提供一套可直接运行、可逐步学习、并适合企业级项目参考的异常处理学习资料。

适用对象：

- 想系统掌握 Python 异常处理的开发者
- 在 FastAPI 项目中遇到错误格式混乱、异常信息丢失的工程师
- 想建立企业级错误架构的同学

---

## 环境要求

- Python 3.11+（ExceptionGroup / `except*` 语法需要 3.11）
- 第 08 章 FastAPI 企业级错误架构需要安装 FastAPI 和 httpx：`uv add fastapi httpx`
- 其他章节仅使用标准库，无第三方依赖

---

## 目录结构

```text
exception教程/
├── README.md                 ← 你在这里
├── roadmap.md                ← 学习路线与排序理由
├── architecture_map.md       ← 异常处理 → 企业架构层映射
├── best_practices.md         ← 推荐做法
├── pitfalls.md               ← 反模式与常见坑
├── examples/
│   ├── 01_basics/
│   │   ├── 01_try_except_else_finally.py
│   │   └── 02_multiple_except.py
│   ├── 02_custom_exceptions/
│   │   ├── 01_basic_custom_exception.py
│   │   └── 02_exception_hierarchy.py
│   ├── 03_exception_chain/
│   │   ├── 01_raise_from.py
│   │   └── 02_anti_pattern_vs_correct.py
│   ├── 04_traceback_logging/
│   │   ├── 01_traceback_format.py
│   │   ├── 02_logging_exc_info.py
│   │   └── 03_json_structured_logging.py
│   ├── 05_context_manager_errors/
│   │   ├── 01_suppress_and_handle.py
│   │   └── 02_cleanup_on_error.py
│   ├── 06_exception_group/
│   │   ├── 01_exception_group_basics.py
│   │   └── 02_except_star.py
│   ├── 07_deep_call_stack/
│   │   ├── 01_propagation_strategy.py
│   │   ├── 02_result_pattern.py
│   │   └── 03_async_propagation.py
│   ├── 08_fastapi_error_architecture/
│   │   ├── 01_layered_error_handling.py
│   │   └── 02_error_code_registry.py
│   ├── 09_testing/
│   │   └── 01_pytest_exception.py
│   └── 10_retry_and_idempotency/
│       └── 01_retry_with_backoff.py
├── templates/
│   ├── README.md
│   ├── error_base.py
│   ├── error_registry.py
│   ├── error_context.py
│   └── fastapi_error_handler.py
└── smoke/
    └── run_all_examples.py
```

---

## 如何运行示例

先进入教程目录：

```bash
cd src/learning_common_lib/python基础/exception教程
```

然后运行任意示例：

```bash
uv run python examples/01_basics/01_try_except_else_finally.py
```

或者从仓库根目录直接运行（需要 shell 支持中文路径）：

```bash
uv run python "src/learning_common_lib/python基础/exception教程/examples/01_basics/01_try_except_else_finally.py"
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
| 1 | 基础语法 | `01_basics/` | try 四件套、多异常捕获与匹配顺序 |
| 2 | 自定义异常体系 | `02_custom_exceptions/` | 结构化字段异常、项目级异常树设计 |
| 3 | 异常链 | `03_exception_chain/` | raise from 显式链、反模式 vs 正确做法 |
| 4 | 日志与 Traceback | `04_traceback_logging/` | traceback 格式化、logging.exception、JSON 结构化日志 |
| 5 | 上下文管理器中的异常 | `05_context_manager_errors/` | suppress、__exit__、资源清理保证 |
| 6 | ExceptionGroup | `06_exception_group/` | ExceptionGroup、except* 与 TaskGroup |
| 7 | 深层调用栈错误传播 | `07_deep_call_stack/` | 5 层调用栈传播策略、Result 模式、async 异常传播 |
| 8 | FastAPI 企业级错误架构 | `08_fastapi_error_architecture/` | 4 层架构、错误码注册表、request_id |
| 9 | 异常测试 | `09_testing/` | pytest.raises 模拟、字段断言、链断言、mock |
| 10 | 重试与退避 | `10_retry_and_idempotency/` | 指数退避、Retry-After、不可重试异常 |

学完示例后，阅读 `templates/` 了解如何将这些知识点封装为企业级可复用组件。

---

## 核心原则

1. **不要吞异常** — 至少记录日志，`except: pass` 是生产事故的温床
2. **用 raise from 保留异常链** — 不要用字符串拼接 re-raise，那会丢失原始 traceback
3. **在边界层转换异常** — 不要在每一层都 catch，仓储层转换一次，服务层转换一次，够了
4. **统一错误响应格式** — 错误码 + 用户可读信息 + request_id，客户端拿到的永远是结构化 JSON
5. **异常是控制流的一部分** — 设计异常体系和设计数据模型一样重要，值得花时间规划

---

## 文档说明

| 文档 | 内容 |
|------|------|
| [roadmap.md](roadmap.md) | 学习路线、排序理由、版本要求 |
| [architecture_map.md](architecture_map.md) | 异常处理 → 企业分层架构映射 |
| [best_practices.md](best_practices.md) | 推荐做法（怎么写好） |
| [pitfalls.md](pitfalls.md) | 反模式与常见坑（怎么写错） |
| [templates/README.md](templates/README.md) | 企业级模板使用说明 |

---

## 学完后你应该具备的能力

- 设计项目级异常层次结构，让不同层的代码能精确捕获和处理异常
- 使用 raise from 保留完整异常链，不丢失任何调试信息
- 在深层调用栈中正确传播和转换异常，避免信息丢失
- 用 ExceptionGroup 和 except* 处理并发场景下的多异常
- 为 FastAPI 项目搭建统一的错误处理架构（全局处理器 + 错误码注册表 + request_id）
- 编写异常安全的上下文管理器，保证资源在任何情况下都能正确清理

---

## 最后建议

异常处理不是"写完业务逻辑后补上的 try/except"，而是架构设计的一部分。好的异常体系和好的数据模型一样，需要提前规划、分层设计、统一约定。当你开始把异常处理当作架构来思考，而不是当作防御性代码来堆砌，代码的可维护性和可调试性会有质的提升。
