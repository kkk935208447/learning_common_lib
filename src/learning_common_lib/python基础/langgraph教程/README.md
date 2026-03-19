# LangGraph 教程（基础 + 高阶 + 企业模板）

本目录面向当前仓库 `langgraph 1.1.x` 环境，围绕 multi-agent、AgenticRAG、生产级编排实践组织教程。它既不是纯 API 摘录，也不是只跑通几个 demo 的示意代码，而是尽量把“能落到真实工程里的 LangGraph 使用方法”讲清楚。

## 删除重置 Redis 内容

如果你在本机反复运行 checkpoint、store、Celery 等示例，建议先清理教程专用 Redis DB，避免不同示例互相污染：

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

说明：

- `db=0`：通常给 checkpoint / Celery broker 使用
- `db=1`：通常给 store / result backend 使用
- `db=2`：通常给业务缓存或实验数据使用

## 定位

从零掌握 LangGraph 状态图编程，覆盖：

1. 图构建、状态管理、条件路由
2. 工具调用、持久化、流式输出
3. 子图组合、人机协作、错误处理
4. 多 Agent 编排、动态并行、记忆系统
5. Functional API、测试调试、生产部署
6. AgenticRAG 双图 / Celery / DAG 调度骨架

说明：

- LangGraph 是本仓库 AgenticRAG 用户检索侧的核心编排引擎
- 教程同时覆盖 Graph API（`StateGraph`）和 Functional API（`@entrypoint` / `@task`）
- 教程主线采用 **async-first** 口径
- `01_graph_fundamentals/01_minimal_graph.py` 与 `01_graph_fundamentals/02_multi_node_chain.py` 保留同步最小对照；其余 **绝大多数主线示例** 默认推荐 `asyncio.run(main()) + ainvoke/astream`
- 所有示例默认使用 `FakeListChatModel`，无需 API key 即可运行
- 需要真实 LLM 时，示例中保留了替换说明

## 适合谁

- 已掌握 Python 异步编程基础（`asyncio` / `async` / `await`）
- 需要在项目中引入 Agent 编排框架
- 希望理解 LangGraph 的执行模型（Pregel superstep、reducer、checkpoint、store）
- 正在构建或准备构建 AgenticRAG / multi-agent 系统
- 希望把教程代码直接迁到业务项目中，而不只是看概念图

## 环境要求

| 依赖 | 版本 / 说明 | 用途 |
|------|-------------|------|
| Python | `>=3.11,<3.12` | 与仓库主环境一致 |
| `langgraph` | 当前仓库锁定 `1.1.x` | 核心框架 |
| `langchain-core` | 随 `langchain` 安装 | 消息类型、Fake Chat Model |
| `langgraph-checkpoint-redis` | 当前仓库已纳入依赖 | Redis checkpoint 集成 |
| `redis` | 本地客户端 | checkpoint / store / Celery |
| `celery[redis]` | 本地客户端 | 任务桥接示例 |
| `fastapi` / `uvicorn` | Web 服务示例 | SSE / 部署 |
| `pydantic` | 运行时校验 | 第 2 章状态建模 |

关于 Redis checkpoint 有两个关键前提：

1. 需要安装 `langgraph-checkpoint-redis`
2. 需要支持 **RediSearch / Redis Stack** 的 Redis 实例  
   普通 Redis 虽然能连通，但可能在初始化时因 `FT._LIST` 等命令缺失而降级

## 环境准备

```bash
# 1. 确保依赖已安装
uv sync

# 2. 如需单独安装 Redis checkpoint 集成
uv add langgraph-checkpoint-redis

# 3. 确保 Redis 已启动（带密码 123456）
# Docker 方式验证:
docker exec <redis容器名> redis-cli -a 123456 ping  # 应返回 PONG

# 或 Python 方式验证:
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"
```

如果你要验证 `langgraph-checkpoint-redis` 的真实能力，除了 Redis 连通外，还需要 Redis 支持 RediSearch。

## 目录结构

```text
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
│   ├── 06_streaming/              ← 流式输出全模式（values/updates/messages/events）
│   ├── 07_subgraph_composition/   ← 子图与图嵌套（含双图架构）
│   ├── 08_human_in_the_loop/      ← 人机协作全模式（dynamic interrupt 为主）
│   ├── 09_error_and_resilience/   ← 容错与降级（safe_node/重试/升级）
│   ├── 10_multi_agent/            ← 多 Agent 架构全谱（5 种模式）
│   ├── 11_dynamic_and_parallel/   ← 动态图与并行（Send/map-reduce）
│   ├── 12_memory_and_store/       ← 短期/长期记忆（含五层记忆架构）
│   ├── 13_functional_api/         ← @entrypoint/@task 函数式 API
│   ├── 14_testing_and_debugging/  ← 测试与调试（单元/集成/Mock LLM）
│   ├── 15_production_deployment/  ← 生产部署全链路（FastAPI SSE/优雅关闭）
│   └── 16_agentic_rag_patterns/   ← AgenticRAG 实战模式（双图/Celery 桥接/DAG 调度）
├── templates/
│   ├── __init__.py
│   ├── README.md
│   ├── state_schemas.py
│   ├── safe_node.py
│   ├── graph_builder.py
│   ├── checkpoint_manager.py
│   ├── multi_agent_orchestrator.py
│   ├── celery_graph_bridge.py
│   └── fastapi_graph_app.py
└── smoke/
    └── run_all_examples.py        ← 一键验证所有示例
```

## 快速开始

```bash
cd src/learning_common_lib/python基础/langgraph教程

# 如果之前运行过其他示例，建议先清理 Redis：
redis-cli -a 123456 -n 0 FLUSHDB
redis-cli -a 123456 -n 1 FLUSHDB
redis-cli -a 123456 -n 2 FLUSHDB

# 运行第一个示例（同步最小对照）
uv run python examples/01_graph_fundamentals/01_minimal_graph.py

# 运行第三个示例（async-first 主线开始）
uv run python examples/01_graph_fundamentals/03_execution_model.py

# 一键验证全部示例
UV_CACHE_DIR=/tmp/uv-cache uv run python smoke/run_all_examples.py
```

当前 smoke 脚本会输出：

- `core`：核心控制流示例
- `integration`：Redis / FastAPI / Celery 集成示例

## LLM 使用说明

教程默认使用：

```python
from langchain_core.language_models.fake_chat_models import FakeListChatModel

llm = FakeListChatModel(responses=["模拟回复"])
```

如果你想使用真实 LLM，在示例文件中找到对应注释并替换：

```python
# from langchain_openai import ChatOpenAI
# llm = ChatOpenAI(model="gpt-4o-mini")
```

注意：

- `FakeListChatModel` 按顺序返回预设响应，适合教学和测试
- 涉及工具调用的示例，通常会手动构造带 `tool_calls` 的 `AIMessage`
- 在当前版本里，`FakeListChatModel` 也能配合 `stream_mode="messages"` 产出 chunk，适合本地流式示例

## Async-First 教程约定

除前两个最小同步例子外，本教程的主线示例优先采用以下写法：

```python
async def main() -> None:
    result = await app.ainvoke(inputs)


if __name__ == "__main__":
    asyncio.run(main())
```

流式主线也优先用：

```python
async for chunk, metadata in app.astream(inputs, stream_mode="messages"):
    ...
```

原因：

- 更贴近生产环境中的 LLM / DB / HTTP / Celery 集成
- 可以避免在教程里形成同步阻塞的坏习惯
- 方便直接迁移到 FastAPI、worker、SSE 等业务代码

## 学习路线概览

| 阶段 | 章 | 主题 | 核心知识点 | 建议时间 |
|------|-----|------|-----------|----------|
| 基础篇 | 01 | 图基础 | StateGraph、add_node/add_edge、compile、ainvoke、Pregel superstep | 半天 |
| 基础篇 | 02 | 状态深入 | TypedDict、Annotated reducer、MessagesState、Pydantic、Channel | 半天 |
| 基础篇 | 03 | 边与路由 | 普通边、条件边、五路路由器、循环守卫 | 半天 |
| 基础篇 | 04 | 工具调用 | @tool、ToolNode、ReAct、工具错误处理 | 半天 |
| 基础篇 | 05 | 检查点 | MemorySaver、thread_id、时间旅行、Redis 持久化 | 半天 |
| 基础篇 | 06 | 流式输出 | values/updates/messages、自定义流、`astream_events()` | 半天 |
| 进阶篇 | 07 | 子图组合 | 子图作为节点、状态映射、Command handoff、双图架构 | 半天 |
| 进阶篇 | 08 | 人机协作 | dynamic interrupt、审批流、静态断点补充 | 半天 |
| 进阶篇 | 09 | 错误与韧性 | safe_node、重试、降级、升级协议 | 1 天 |
| 进阶篇 | 10 | 多 Agent | Supervisor、Swarm、Plan-Execute-Replan、层级 Agent、黑板模式 | 1 天 |
| 进阶篇 | 11 | 动态与并行 | Send fan-out、Send vs Command、configurable、map-reduce | 半天 |
| 进阶篇 | 12 | 记忆与存储 | 短期记忆、长期记忆、五层记忆架构 | 半天 |
| 进阶篇 | 13 | 函数式 API | @entrypoint、@task、Functional vs Graph API | 半天 |
| 工程篇 | 14 | 测试与调试 | 节点单元测试、图集成测试、Mock LLM、Mermaid 调试 | 1 天 |
| 工程篇 | 15 | 生产部署 | FastAPI SSE、可观测性、Double-texting、优雅关闭 | 1 天 |
| 工程篇 | 16 | AgenticRAG | GlobalGraph/SubtaskGraph、Celery bridge、DAG dispatch | 1 天 |

第 16 章直接对应：

- `案例/用户AgenticRAG检索/架构设计规划.md`
- `案例/用户AgenticRAG检索/技术拆解.md`

## Graph API vs Functional API

LangGraph 提供两种 API 风格，教程都会覆盖：

| 维度 | Graph API（第 1-12 章） | Functional API（第 13 章） |
|------|------------------------|--------------------------|
| 定义方式 | `StateGraph` + `add_node` + `add_edge` | `@entrypoint` + `@task` |
| 控制流 | 边和条件边 | 原生 `if` / `for` / `while` |
| 状态管理 | TypedDict + reducer + channel | 函数参数 |
| 可视化 | `draw_mermaid()` 支持 | 不支持 |
| 并行 fan-out | `Send` 原生支持 | 需自行组织 |
| 适用场景 | 复杂拓扑、多 Agent、需要可视化 | 线性流程、轻量 workflow |

建议：

- 复杂拓扑、多分支、循环、子图、multi-agent：优先 Graph API
- 简单线性 workflow：可用 Functional API
- 不确定时：先用 Graph API，它更接近本仓库 AgenticRAG 实现

## Redis 连接约定

```text
checkpoint: redis://:123456@localhost:6379/0
store:      redis://:123456@localhost:6379/1
cache:      redis://:123456@localhost:6379/2
```

说明：

- 分库能避免不同教程组件的 key 冲突
- 对 checkpoint 来说，推荐 Redis Stack / RediSearch 能力更完整
- 普通 Redis 不一定支持 `langgraph-checkpoint-redis` 的所有命令

thread_id 命名约定（参考 AgenticRAG）：

- `GlobalGraph`：`tenant:{tenant_id}:task:{task_id}`
- `SubtaskGraph`：`tenant:{tenant_id}:task:{task_id}:plan:{plan_version}:subtask:{subtask_code}:exec:{execution_id}`

## 章节重点

### 基础能力

- `01_graph_fundamentals`：图的最小结构、superstep、可视化
- `02_state_deep_dive`：TypedDict、Pydantic、MessagesState、reducer
- `03_edges_and_routing`：普通边、条件边、循环 guard

### 工程能力

- `05_checkpointing`：thread_id、checkpoint、恢复、时间旅行
- `06_streaming`：`astream(..., stream_mode=...)` 与 `astream_events(...)` 的边界
- `08_human_in_the_loop`：动态 `interrupt()` 为主，静态断点为补充
- `09_error_and_resilience`：safe node、retry、fallback、escalation

### 架构能力

- `10_multi_agent`：supervisor、swarm、plan-execute-replan、blackboard
- `11_dynamic_and_parallel`：`Send`、`Command`、map-reduce
- `12_memory_and_store`：checkpoint 与 store 的职责边界

### AgenticRAG 映射

- `16_agentic_rag_patterns/01_global_graph_skeleton.py`
  - 控制平面、等待态、clarify 恢复
- `16_agentic_rag_patterns/02_subtask_graph_skeleton.py`
  - 子任务局部执行闭环
- `16_agentic_rag_patterns/03_celery_bridge.py`
  - dispatch -> waiting -> resume
- `16_agentic_rag_patterns/04_dag_dispatch_pattern.py`
  - READY batch dispatch + fan-out

## 阅读建议

1. 先按路线图逐个运行示例，再回头读对应说明
2. 需要看整体架构时查 [architecture_map.md](./architecture_map.md)
3. 需要看实践约束时查 [best_practices.md](./best_practices.md)
4. 遇到奇怪 bug 或行为不符时查 [pitfalls.md](./pitfalls.md)
5. 最后用 `smoke/run_all_examples.py` 做回归验证

## 注意事项

- 示例默认尽量自包含，不做跨 example 导入
- 模板代码放在 `templates/`，面向复用，不面向最小教学路径
- Redis / Celery / FastAPI 章节是工程样板，不是所有项目都必须引入
- 如果你只想学 LangGraph 控制流，至少先完成 `01`、`02`、`03`、`05`、`06`
