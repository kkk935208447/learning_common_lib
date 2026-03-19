# LangGraph 架构全景图

## 核心概念

```
┌─────────────────────────────────────────────────┐
│                   StateGraph                     │
│                                                  │
│  ┌──────┐    Edge     ┌──────┐    Edge    ┌───┐ │
│  │ Node ├────────────→│ Node ├───────────→│END│ │
│  │  A   │             │  B   │            └───┘ │
│  └──────┘             └──┬───┘                  │
│                          │ Conditional Edge     │
│                     ┌────┴────┐                 │
│                     │ Node C  │                 │
│                     └─────────┘                 │
│                                                  │
│  State: TypedDict + Channel (Reducer)           │
└─────────────────────────────────────────────────┘
```

- Graph: 有向图，定义节点和边的拓扑关系
- State: TypedDict 定义的状态容器，在节点间传递
- Node: 接收 state、返回 state 更新的函数
- Edge: 节点间的连接，分为普通边和条件边
- Channel: 状态字段的合并策略（如 `add_messages` reducer）

## 执行模型：Pregel Superstep

```
Superstep 0          Superstep 1          Superstep 2
┌─────────┐         ┌─────────┐         ┌─────────┐
│ Node A  │ ──────→ │ Node B  │ ──────→ │ Node C  │
│ (entry) │         │         │         │  (end)   │
└─────────┘         └─────────┘         └─────────┘
     │                   │                   │
     ▼                   ▼                   ▼
  State v0            State v1            State v2
```

每个 superstep：
1. 读取当前 state
2. 执行当前活跃节点
3. 通过 channel reducer 合并状态更新
4. 写入新 state，确定下一步节点

## 持久化层：Checkpointer

```
Graph Execution ──→ Checkpointer ──→ Storage Backend
                         │
                    ┌────┴────┐
                    │ Memory  │  开发/测试
                    │ SQLite  │  单机生产
                    │ Redis   │  分布式生产
                    │ Postgres│  企业级
                    └─────────┘
```

Checkpoint 记录每个 superstep 的完整状态快照，支持：
- 时间旅行（回溯到任意步骤）
- 断点续跑（Human-in-the-Loop）
- 故障恢复

## 流式层：Stream Modes

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `values` | 每步输出完整 state | 调试、状态监控 |
| `updates` | 每步输出 state diff | 前端增量更新 |
| `messages` | 输出 LLM token 流 | 聊天界面 |
| `custom` | 自定义事件 | 进度条、日志 |

## 多 Agent 模式分类

```
1. Supervisor 模式          2. 网状协作模式
   ┌──────────┐               ┌───┐ ←→ ┌───┐
   │Supervisor│               │ A │     │ B │
   └────┬─────┘               └─┬─┘     └─┬─┘
   ┌────┼────┐                  │    ↕     │
   ▼    ▼    ▼                ┌─┴──────────┴─┐
  W_A  W_B  W_C              │      C        │
                              └───────────────┘

3. 层级模式                  4. Plan-Execute-Replan
   ┌─────────┐                Plan → Execute → Replan
   │Top Super│                  ↑                 │
   └────┬────┘                  └─────────────────┘
   ┌────┴────┐
   ▼         ▼
 Sub_A     Sub_B
 ┌┴┐       ┌┴┐
 W W       W W
```

## AgenticRAG 双图架构映射

```
┌─────────────────────────────────────────┐
│            Orchestrator Graph            │
│  plan → retrieve → grade → generate     │
│    ↑                          │         │
│    └──── replan ←─────────────┘         │
└─────────────────────────────────────────┘
                    │
                    ▼ (Celery dispatch)
┌─────────────────────────────────────────┐
│            Worker Graph                  │
│  parse → search → rank → format         │
└─────────────────────────────────────────┘
```

对应 `templates/` 模块：
- `state_schemas.py` → 状态定义
- `safe_node.py` → 节点错误处理
- `graph_builder.py` → 图构建
- `checkpoint_manager.py` → 持久化
- `multi_agent_orchestrator.py` → 多 Agent 编排
- `celery_graph_bridge.py` → Celery 桥接
- `fastapi_graph_app.py` → Web 服务
