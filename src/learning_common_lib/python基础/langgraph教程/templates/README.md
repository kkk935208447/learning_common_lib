# templates/ — 可复用模板模块

为 LangGraph 项目提供生产级可复用组件。

## 模块一览

| 模块 | 用途 | 关键导出 |
|------|------|----------|
| `state_schemas.py` | 状态 schema 基类 | `BaseState`, `AgentState`, `MessageAgentState` |
| `teaching_contracts.py` | 教程共享契约 | `PlanNodeSpec`, `WorkerTask`, `WorkerResultEnvelope`, `EscalationReport` |
| `safe_node.py` | 节点错误处理中间件 | `@safe_node`, `NodeError`, `ErrorSeverity` |
| `graph_builder.py` | 图构建工厂 | `GraphBuilder`, `build_graph()` |
| `runtime_settings.py` | Redis-first 运行时配置 | `RedisRuntimeSettings`, `DEFAULT_RUNTIME_SETTINGS` |
| `checkpoint_manager.py` | Checkpoint 管理 | `CheckpointManager`, `get_checkpointer()` |
| `store_manager.py` | Store 管理 | `StoreManager`, `ResilientStore`, `get_store()` |
| `multi_agent_orchestrator.py` | 多 Agent 编排 | `Orchestrator`, `SupervisorAgent`, `WorkerAgent` |
| `celery_graph_bridge.py` | Celery 桥接 | `dispatch_to_celery()`, `accept_or_mark_stale()`, `resume_orchestrator()` |
| `fastapi_graph_app.py` | FastAPI 集成 | `create_graph_app()`, `graph_lifespan` |

## 快速使用

```python
from templates import GraphBuilder, AgentState, safe_node

# 1. 定义节点
@safe_node(node_name="my_node", timeout_s=10)
async def my_node(state: dict) -> dict:
    return {"next_action": "continue"}

# 2. 构建图
graph = (
    GraphBuilder(AgentState)
    .add_node("my_node", my_node, safe=False)  # 已手动包装
    .set_entry("my_node")
    .build()
)

# 3. 执行
result = await graph.ainvoke({"iteration": 0})
```

## Redis-first 运行时

```python
from templates import DEFAULT_RUNTIME_SETTINGS

print(DEFAULT_RUNTIME_SETTINGS.checkpoint_url)
print(DEFAULT_RUNTIME_SETTINGS.store_url)
print(DEFAULT_RUNTIME_SETTINGS.global_thread_id("acme", 42))
```

> Redis Stack / RediSearch 注意事项

如果你使用的是 **Redis Stack（包含 RediSearch）**，Store 在初始化时会尝试创建索引。
多数情况下 RediSearch **仅允许在 db=0 上创建索引**；若 `store_url` 指向 `db!=0`，你会看到类似错误：

- `RedisSearchError: ... Cannot create index on db != 0`

解决方式（推荐其一）：

- **直接用环境变量指定 Store 使用 db=0**：`LANGGRAPH_REDIS_STORE_DB=0`
- **或保持默认**：本模板已将 `store_db` 默认值改为 0（仍可用环境变量覆盖）

## Checkpoint / Store 管理

```python
from templates import CheckpointManager, StoreManager

checkpoint_mgr = CheckpointManager()
store_mgr = StoreManager()

checkpointer = await checkpoint_mgr.get_checkpointer()
store = await store_mgr.get_store()

# Redis 不可用时会降级，但会明确记录 backend 与原因
print(checkpoint_mgr.backend, checkpoint_mgr.degraded, checkpoint_mgr.last_error)
print(store.backend, store.degraded, store.last_error)
```

如果你更喜欢 helper 风格：

```python
from templates import get_checkpointer, get_store

checkpointer = await get_checkpointer()
store = await get_store()

print(checkpointer.backend, checkpointer.degraded, checkpointer.last_error)
print(store.backend, store.degraded, store.last_error)
await checkpointer.aclose()
await store.aclose()
```

## 多 Agent 编排

```python
from templates import SupervisorAgent, WorkerAgent

workers = [
    WorkerAgent(name="researcher", description="搜索信息", graph=research_graph),
    WorkerAgent(name="writer", description="撰写内容", func=write_fn),
]
supervisor = SupervisorAgent(workers, llm=my_llm)
graph = supervisor.build_graph()
```

## Celery 桥接

```python
from templates import accept_or_mark_stale, dispatch_to_celery

# 在图节点内分发 Celery 任务（不阻塞事件循环）
envelope = await dispatch_to_celery(
    "tasks.process",
    {"data": "..."},
    queue="heavy",
    thread_id="tenant:acme:task:42",
    execution_id="exec-001",
)
print(envelope["task_id"])

decision = accept_or_mark_stale(
    {"execution_id": "exec-001", "status": "COMPLETED"},
    current_execution_id="exec-001",
)
print(decision)
```

## FastAPI 集成

```python
from templates import create_graph_app

app = create_graph_app(title="My LangGraph API")
# uvicorn main:app --reload
```

模板默认策略：

- checkpoint：Redis-first，失败降级到 `MemorySaver`
- store：Redis-first，失败降级到 `InMemoryStore`
- checkpoint / store 默认共享 db=0，通过不同 prefix 隔离
- FastAPI SSE：token channel + store-backed progress events replay
- Celery：统一使用 runtime settings 中的 Redis URL

当前模板边界：

- FastAPI 模板已经包含 heartbeat / `Last-Event-ID` / store-backed replay 的最小语义
- 但它仍然不是完整生产实现：未覆盖 client disconnect、事件 ID 多 writer 原子性、retention/trim
- 因此它是“production-shaped skeleton”，不是“直接上线模板”

## 何时进入模板层

建议按下面这条规则判断：

- 如果你还在理解 `graph worker / stale fencing / replay / structured approval` 为什么存在，先停留在 `examples/` 的 realistic example
- 只有当你已经知道这些语义为什么需要，并准备抽出复用骨架时，再进入 `templates/`

## 教程映射

如果你是从 `examples/` 迁移到模板层，建议按下面的映射阅读：

- `09_error_and_resilience/*` → `safe_node.py`
- `05_checkpointing/*` → `checkpoint_manager.py`
- `12_memory_and_store/*` → `store_manager.py`
- `10_multi_agent/06_supervisor_with_subgraphs.py` → `multi_agent_orchestrator.py`
- `16_agentic_rag_patterns/03_celery_bridge.py` / `06_resume_orchestrator_contract.py` → `celery_graph_bridge.py`

注意：

- 模板是“可复用骨架”，不是“最小教学例子”
- 如果你还停留在 toy 示例阶段，先读 `examples/` 里的真实版，再看模板层
