# templates/ — 可复用模板模块

为 LangGraph 项目提供生产级可复用组件。

## 模块一览

| 模块 | 用途 | 关键导出 |
|------|------|----------|
| `state_schemas.py` | 状态 schema 基类 | `BaseState`, `AgentState`, `MessageAgentState` |
| `safe_node.py` | 节点错误处理中间件 | `@safe_node`, `NodeError`, `ErrorSeverity` |
| `graph_builder.py` | 图构建工厂 | `GraphBuilder`, `build_graph()` |
| `checkpoint_manager.py` | Checkpoint 管理 | `CheckpointManager`, `get_checkpointer()` |
| `multi_agent_orchestrator.py` | 多 Agent 编排 | `Orchestrator`, `SupervisorAgent`, `WorkerAgent` |
| `celery_graph_bridge.py` | Celery 桥接 | `dispatch_to_celery()`, `resume_orchestrator()` |
| `fastapi_graph_app.py` | FastAPI 集成 | `create_graph_app()`, `graph_lifespan` |

## 快速使用

```python
from templates import GraphBuilder, AgentState, safe_node

# 1. 定义节点
@safe_node(node_name="my_node", timeout_s=10)
async def my_node(state: dict) -> dict:
    return {**state, "next_action": "continue"}

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

## Checkpoint 管理

```python
from templates import CheckpointManager

mgr = CheckpointManager(redis_url="redis://:123456@localhost:6379/0")
checkpointer = await mgr.get_checkpointer()  # Redis 不可用自动降级为内存
```

## 多 Agent 编排

```python
from templates import SupervisorAgent, WorkerAgent

workers = [
    WorkerAgent(name="researcher", description="搜索信息", func=research_fn),
    WorkerAgent(name="writer", description="撰写内容", func=write_fn),
]
supervisor = SupervisorAgent(workers, llm=my_llm)
graph = supervisor.build_graph()
```

## Celery 桥接

```python
from templates import dispatch_to_celery

# 在图节点内分发 Celery 任务（不阻塞事件循环）
task_id = await dispatch_to_celery("tasks.process", {"data": "..."}, queue="heavy")
```

## FastAPI 集成

```python
from templates import create_graph_app

app = create_graph_app(title="My LangGraph API")
# uvicorn main:app --reload
```
