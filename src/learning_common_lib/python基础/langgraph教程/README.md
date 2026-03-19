# LangGraph 教程（基础 + 高阶 + 企业模板）

## 删除重置 Redis 内容

```python
import redis as redis_lib
def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2):
        client = redis_lib.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=db,
            socket_connect_timeout=3,
        )
        try:
            client.flushdb()
            print(f"  db={db} 已清空")
        finally:
            client.close()
reset_tutorial_redis()
```

## 定位

从零掌握 LangGraph 状态图编程，覆盖图构建、状态管理、条件路由、工具调用、持久化、流式输出、子图组合、人机协作、错误处理、多 Agent 编排、动态并行、记忆存储、函数式 API、测试调试、生产部署、AgenticRAG 实战模式共 16 章渐进式示例，外加一套企业级可复用模板。

说明：
- LangGraph 是 AgenticRAG 用户检索侧的核心编排引擎
- 教程同时覆盖 Graph API（StateGraph）和 Functional API（@entrypoint/@task）
- 所有示例默认使用 `FakeListChatModel` 模拟 LLM，无需 API key 即可运行
- 需要真实 LLM 时，注释中说明了如何替换为 `ChatOpenAI` 等

## 适合谁

- 已掌握 Python 异步编程基础（asyncio / async-await）
- 需要在项目中引入 Agent 编排框架
- 希望理解 LangGraph 底层执行模型（Pregel superstep、Channel、Checkpoint）
- 正在构建或准备构建 AgenticRAG 系统

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | ≥3.11 | 运行环境 |
| langgraph | ≥0.2 | 核心框架（StateGraph、Pregel 引擎） |
| langgraph-checkpoint-redis | ≥0.1 | Redis Checkpoint 持久化（第 5、16 章） |
| langchain-core | ≥0.3 | 消息抽象、工具定义、回调系统 |
| langchain-community | ≥0.3 | FakeListChatModel 等测试工具 |
| redis | ≥5.0 | Redis 客户端（Checkpoint + Store） |
| celery[redis] | ≥5.3 | 任务队列桥接（第 16 章） |
| fastapi | ≥0.110 | Web 服务集成（第 15 章） |
| uvicorn | ≥0.29 | ASGI 服务器 |
| pydantic | ≥2.0 | 状态验证（第 2 章） |

## 环境准备

```bash
# 1. 确保 Redis 已启动（带密码 123456）
# Docker 方式验证:
docker exec <redis容器名> redis-cli -a 123456 ping  # 应返回 PONG
# 或 Python 方式验证:
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 2. 安装依赖
uv add langgraph langgraph-checkpoint-redis langchain-core langchain-community redis "celery[redis]" fastapi uvicorn pydantic
# 或
pip install langgraph langgraph-checkpoint-redis langchain-core langchain-community redis "celery[redis]" fastapi uvicorn pydantic
```

## 目录结构

```
langgraph教程/
├── README.md                  ← 本文件
├── roadmap.md                 ← 学习路线图
├── architecture_map.md        ← 架构全景图
├── best_practices.md          ← 最佳实践
├── pitfalls.md                ← 常见陷阱
├── examples/
│   ├── 01_graph_fundamentals/     ← 图的最小单元到执行模型
│   ├── 02_state_deep_dive/        ← 状态系统全貌：TypedDict、Reducer、Channel
│   ├── 03_edges_and_routing/      ← 边类型与条件路由（含五路路由器）
│   ├── 04_tool_calling/           ← LLM 工具调用全链路（含 ReAct Agent）
│   ├── 05_checkpointing/          ← 持久化与恢复（MemorySaver → Redis）
│   ├── 06_streaming/              ← 流式输出全模式（values/updates/events/token）
│   ├── 07_subgraph_composition/   ← 子图与图嵌套（含双图架构）
│   ├── 08_human_in_the_loop/      ← 人机协作全模式（interrupt/审批流）
│   ├── 09_error_and_resilience/   ← 容错与降级（safe_node/重试/升级）
│   ├── 10_multi_agent/            ← 多 Agent 架构全谱（5 种模式）
│   ├── 11_dynamic_and_parallel/   ← 动态图与并行（Send/map-reduce）
│   ├── 12_memory_and_store/       ← 短期/长期记忆（含五层记忆架构）
│   ├── 13_functional_api/         ← @entrypoint/@task 函数式 API
│   ├── 14_testing_and_debugging/  ← 测试与调试（单元/集成/Mock LLM）
│   ├── 15_production_deployment/  ← 生产部署全链路（FastAPI SSE/优雅关闭）
│   └── 16_agentic_rag_patterns/   ← AgenticRAG 实战模式（双图/Celery 桥接/DAG 调度）
├── templates/
│   ├── __init__.py                ← 公开 API 导出
│   ├── README.md                  ← 模板使用说明
│   ├── state_schemas.py           ← 可复用状态 schema 基类
│   ├── safe_node.py               ← 节点错误处理中间件（超时 + 异常分级）
│   ├── graph_builder.py           ← 生产级图构建工厂
│   ├── checkpoint_manager.py      ← Checkpoint 管理器（Redis/内存自动切换）
│   ├── multi_agent_orchestrator.py ← 多 Agent 编排骨架
│   ├── celery_graph_bridge.py     ← LangGraph + Celery 桥接
│   └── fastapi_graph_app.py       ← FastAPI + LangGraph 集成
└── smoke/
    └── run_all_examples.py        ← 一键验证所有示例
```

## 快速开始

```bash
cd src/learning_common_lib/python基础/langgraph教程

# 如果之前运行过其他示例，建议先清理 Redis：
redis-cli -a 123456 -n 0 FLUSHDB && redis-cli -a 123456 -n 1 FLUSHDB

# 运行第一个示例
uv run python examples/01_graph_fundamentals/01_minimal_graph.py

# 一键验证全部示例（自动逐个运行）
uv run python smoke/run_all_examples.py
```

## LLM 使用说明

教程默认使用 `FakeListChatModel` 模拟 LLM 响应，无需 API key 即可运行所有示例。

如果你想使用真实 LLM，在示例文件中找到类似注释并替换：

```python
# 默认：FakeListChatModel（无需 API key）
from langchain_community.chat_models import FakeListChatModel
llm = FakeListChatModel(responses=["模拟回复"])

# 替换为真实 LLM（需要 API key）：
# from langchain_openai import ChatOpenAI
# llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-...")
```

注意：
- `FakeListChatModel` 按顺序返回预设的响应列表，适合教学和测试
- 涉及工具调用的示例（第 4 章）已预设了包含 `tool_calls` 的 AIMessage
- 真实 LLM 的行为可能与预设响应不同，但图的执行逻辑一致

## 学习路线概览

| 阶段 | 章 | 主题 | 核心知识点 | 建议时间 |
|------|-----|------|-----------|----------|
| 基础篇 | 01 | 图基础 | StateGraph、add_node/add_edge、compile、invoke、Pregel superstep | 半天 |
| 基础篇 | 02 | 状态深入 | TypedDict、Annotated reducer、MessagesState、Pydantic 状态、Channel 类型 | 半天 |
| 基础篇 | 03 | 边与路由 | 普通边、条件边、五路路由器（step_gate_router）、循环守卫（loop_guard） | 半天 |
| 基础篇 | 04 | 工具调用 | @tool、bind_tools、ToolNode、ReAct Agent 循环、工具错误处理 | 半天 |
| 基础篇 | 05 | 检查点 | MemorySaver、thread_id 隔离、时间旅行、Redis 持久化、ResilientCheckpointer | 半天 |
| 基础篇 | 06 | 流式输出 | values/updates/events/messages 四种模式、token 级流式、SSE 约束 | 半天 |
| 进阶篇 | 07 | 子图组合 | 子图作为节点、状态映射、Command handoff、双图架构 | 半天 |
| 进阶篇 | 08 | 人机协作 | interrupt_before/after、动态中断、审批流、Clarify 模式 | 半天 |
| 进阶篇 | 09 | 错误与韧性 | safe_node 装饰器、指数退避重试、多级降级、升级协议 | 1 天 |
| 进阶篇 | 10 | 多 Agent | Supervisor、Swarm、Plan-Execute-Replan、层级 Agent、黑板模式 | 1 天 |
| 进阶篇 | 11 | 动态与并行 | Send API fan-out、Send vs Command、configurable、map-reduce | 半天 |
| 进阶篇 | 12 | 记忆与存储 | 短期记忆（State）、长期记忆（Store）、五层记忆架构 | 半天 |
| 进阶篇 | 13 | 函数式 API | @entrypoint、@task、Functional vs Graph API 对比 | 半天 |
| 工程篇 | 14 | 测试与调试 | 节点单元测试、图集成测试、Mock LLM、Mermaid 调试 | 1 天 |
| 工程篇 | 15 | 生产部署 | FastAPI SSE、可观测性、Double-texting、优雅关闭 | 1 天 |
| 工程篇 | 16 | AgenticRAG | GlobalGraph/SubtaskGraph 骨架、Celery 桥接、DAG 调度 | 1 天 |

第 16 章中的 AgenticRAG 模式直接对应 `案例/用户AgenticRAG检索/技术拆解.md` 的设计：
- `01_global_graph_skeleton.py`：GlobalState TypedDict + step_gate_router 五路分发
- `02_subtask_graph_skeleton.py`：SubtaskState TypedDict + loop_guard_router 循环守卫
- `03_celery_bridge.py`：resume_orchestrator 模式（禁止在图节点内 .get()）
- `04_dag_dispatch_pattern.py`：compute_ready_codes + claim + dispatch 批次调度

## Graph API vs Functional API

LangGraph 提供两种 API 风格，教程都有覆盖：

| 维度 | Graph API（第 1-12 章） | Functional API（第 13 章） |
|------|------------------------|--------------------------|
| 定义方式 | `StateGraph` + `add_node` + `add_edge` | `@entrypoint` + `@task` |
| 控制流 | 边和条件边 | 原生 `if`/`for`/`while` |
| 状态管理 | TypedDict + Channel + Reducer | 函数参数 |
| 可视化 | `draw_mermaid()` 支持 | 不支持 |
| 适用场景 | 复杂拓扑、多 Agent、需要可视化 | 简单线性流程、快速原型 |

建议：
- 复杂拓扑（多分支、循环、子图）→ Graph API
- 简单线性流程 → Functional API
- 不确定时 → 先用 Graph API，它覆盖所有场景

## Redis 连接约定

```
checkpoint:  redis://:123456@localhost:6379/0   ← Checkpoint 持久化
store:       redis://:123456@localhost:6379/1   ← Store 长期记忆
cache:       redis://:123456@localhost:6379/2   ← 业务缓存
```

分库避免 key 冲突，带密码认证。

thread_id 命名约定（参考 AgenticRAG）：
- GlobalGraph: `tenant:{tenant_id}:task:{task_id}`
- SubtaskGraph: `tenant:{tenant_id}:task:{task_id}:plan:{plan_version}:subtask:{subtask_code}:exec:{execution_id}`

详细路线图见 [roadmap.md](roadmap.md)。
