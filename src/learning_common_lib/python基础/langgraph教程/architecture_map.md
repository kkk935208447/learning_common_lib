# LangGraph 架构全景图

本文件恢复了原始教程中大部分架构图、映射关系和概念说明，同时按当前仓库 `langgraph 1.1.x` 与 async-first 教学口径统一修正。

## 1. 核心分层架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        用户代码层 (User Code)                        │
│  定义 State、Node 函数、Edge 路由逻辑、工具                            │
│  graph = StateGraph(State)                                          │
│  graph.add_node("agent", call_model)                                │
│  graph.add_conditional_edges("agent", should_continue)              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    StateGraph API (图构建层)                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐               │
│  │ add_node │   │ add_edge │   │ add_conditional  │               │
│  │          │   │          │   │ _edges           │               │
│  └──────────┘   └──────────┘   └──────────────────┘               │
│  compile() → 生成 CompiledGraph (Pregel 实例)                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Pregel 执行引擎 (Runtime)                          │
│  Superstep 循环 → 节点调度 → 并行执行 → reducer 合并                  │
│  支持: invoke / ainvoke / stream / astream / astream_events         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
             ┌───────────┐ ┌──────────┐ ┌──────────┐
             │  Channel  │ │Checkpoint│ │  Store   │
             │  语义层    │ │  持久化   │ │ 长期记忆  │
             └───────────┘ └──────────┘ └──────────┘
```

当前教程建议：

- Graph API 是复杂拓扑、多 Agent、双图架构的主线
- Functional API 更适合线性 workflow
- 运行入口默认优先 `ainvoke` / `astream`

## 2. Pregel 执行模型详细图

```text
                         Superstep N 完整流程
┌─────────────────────────────────────────────────────────────────────┐
│  ① 读取 state / checkpoint   ② 确定活跃节点   ③ 执行节点             │
│  ┌──────────────┐          ┌──────────────┐  ┌──────────────┐       │
│  │ 从 checkpoint │   →      │ 根据边和路由   │  │ node_A()     │       │
│  │ 恢复上下文     │          │ 判断哪些节点   │  │ node_B()     │       │
│  │              │          │ 应被激活      │  │ (可并行)     │       │
│  └──────────────┘          └──────────────┘  └──────┬───────┘       │
│                                                      │               │
│  ⑧ 决定下一步             ⑦ 保存 checkpoint    ⑥ reducer 合并       │
│  ┌──────────────┐         ┌──────────────┐      ┌──────────────┐    │
│  │ 条件边 / END  │   ←     │ checkpointer │  ←   │ 写入 channel  │    │
│  │ 下一轮激活集   │         │ / state snap │      │ / state 字段  │    │
│  └──────────────┘         └──────────────┘      └──────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

关键点：

- 同一 superstep 内的多个节点共享同一输入快照，互相看不到彼此当前轮的写入
- reducer 决定状态字段的合并语义
- checkpoint 保存的是 state 演进，不是你手工维护的中间对象图

## 3. Channel 系统详图

```text
                        Channel 类型体系
┌─────────────────────────────────────────────────────────────────────┐
│  LastValue（默认）                                                  │
│    - 语义：后写覆盖（last-write-wins）                              │
│    - 用途：普通标量字段（status、next_action、error）               │
│                                                                     │
│  BinaryOperatorAggregate（Annotated reducer）                       │
│    - 语义：f(left, right) → merged                                  │
│    - 用途：列表追加、计数器累加、集合合并                            │
│    - 示例：                                                         │
│      Annotated[list, operator.add]                                  │
│      Annotated[list, add_messages]                                  │
│      Annotated[int, lambda a, b: a + b]                             │
│                                                                     │
│  EphemeralValue（概念层）                                           │
│    - 语义：一次性信号 / 当前 superstep 可见                         │
│    - 教程里通过“读取后清空”逻辑近似模拟                             │
└─────────────────────────────────────────────────────────────────────┘
```

数据流：

- 节点返回 `dict`
- LangGraph 根据 schema / reducer 写入 channel
- superstep 边界后对下游可见

## 4. Checkpoint 流转图

```text
  ainvoke(input, config={"configurable": {"thread_id": "t1"}})
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ CP-0     │ →  │ CP-1     │ →  │ CP-2     │ →  │ CP-3     │
│ (初始)   │    │ (step 1) │    │ (step 2) │    │ (step 3) │
│ input    │    │ +node_A  │    │ +node_B  │    │ +node_C  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                      │                               │
                      ▼ 时间旅行                       ▼ 最新状态
                ┌──────────┐                    aget_state(config)
                │ 从 CP-1  │
                │ 分叉新线  │
                └──────────┘
```

存储后端：

```text
MemorySaver          → 开发 / 测试（进程内，重启丢失）
Redis checkpointer   → 跨进程恢复（需要 Redis Stack / RediSearch）
PostgresSaver        → 事务型生产存储
```

thread_id 命名约定（参考 AgenticRAG）：

- `GlobalGraph`: `tenant:{tenant_id}:task:{task_id}`
- `SubtaskGraph`: `tenant:{tenant_id}:task:{task_id}:plan:{plan_version}:subtask:{subtask_code}:exec:{execution_id}`

## 5. 流式输出模式对比

### A. 主流业务流：`astream(..., stream_mode=...)`

```text
graph.astream(..., stream_mode="values")
graph.astream(..., stream_mode="updates")
graph.astream(..., stream_mode="messages")
graph.astream(..., stream_mode="custom")
```

| 模式 | 数据粒度 | 适用场景 | 数据量 |
|------|----------|----------|--------|
| `values` | 完整 state 快照 | 调试、状态监控 | 大 |
| `updates` | 节点级增量 | 前端状态同步 | 中 |
| `messages` | token / message chunk | 聊天 SSE、逐字输出 | 小 |
| `custom` | 自定义事件 | 进度通知、业务埋点 | 按需 |

### B. 事件观测流：`astream_events(...)`

```text
graph.astream_events(..., version="v2")
```

用途：

- 调试
- trace
- observability
- 查看子图、工具、模型事件

说明：

- 旧文档里常把“events”直接和 stream_mode 并列
- 当前教程明确区分：`astream_events()` 是事件追踪接口，不是默认聊天流式接口
- 当前教程还额外强调：token 流只负责即时渲染，`store-backed progress events` 才是 replay 真理源

## 6. 多 Agent 模式架构图

```text
模式 1: Supervisor（中心调度）
┌─────────────────────────────────────────┐
│              Supervisor                  │
│         ┌──────┼──────┐                 │
│         ▼      ▼      ▼                 │
│     Worker_A Worker_B Worker_C          │
│         │      │      │                 │
│         └──────┼──────┘                 │
│                ▼                         │
│           共享 State / 工件               │
└─────────────────────────────────────────┘

模式 2: Swarm（去中心化）
┌─────────────────────────────────────────┐
│     Agent_A ←──handoff──→ Agent_B       │
│        ↕                     ↕           │
│     Agent_C ←──handoff──→ Agent_D       │
│              共享 State                  │
└─────────────────────────────────────────┘

模式 3: Plan-Execute-Replan
┌─────────────────────────────────────────┐
│  Planner → Executor → Evaluator         │
│     ↑                      │             │
│     └──── Replanner ←──────┘             │
│         (max_replan ≤ 3)                 │
└─────────────────────────────────────────┘

模式 4: 层级 Agent（双图架构）
┌─────────────────────────────────────────┐
│  GlobalGraph（控制平面）                  │
│                 │                         │
│                 ▼                         │
│          SubtaskGraph（执行平面）         │
└─────────────────────────────────────────┘

模式 5: 黑板模式
┌─────────────────────────────────────────┐
│           Blackboard (共享 State)         │
│  每个 Agent 只写自己负责的字段             │
└─────────────────────────────────────────┘
```

当前教程推荐：

- 大多数企业场景优先 `Supervisor` / `GlobalGraph`
- `Swarm` 作为 handoff 思路补充
- 双图架构用于复杂 AgenticRAG
- 真实版 graph worker 见 `10_multi_agent/06_supervisor_with_subgraphs.py`
- 子图把控制权交回父图时，参考 `07_subgraph_composition/05_command_parent_handoff.py`

## 7. AgenticRAG 双图架构详细图

详情可对照：

- `案例/用户AgenticRAG检索/架构设计规划.md`
- `案例/用户AgenticRAG检索/技术拆解.md`

```text
┌────────────────── GlobalGraph（控制平面）──────────────────┐
│  GlobalState:                                             │
│    task_id / request_id / waiting_reason / current_execution_id │
│    latest_result_ref / next_action                        │
│                                                           │
│  planner → clarify → scheduler → wait_subtasks → step_gate│
│                │                │               │          │
│                │                └─ dispatch ----┘          │
│                └─ WAITING_CLARIFICATION                    │
│                              finalize → output            │
└──────────────────────────────┬────────────────────────────┘
                               │
                               ▼
┌────────────────── SubtaskGraph（局部执行平面）──────────────┐
│  SubtaskState:                                            │
│    subtask_code / execution_id / query / evidence_ref     │
│    eval_score / result_envelope                           │
│                                                           │
│  prepare → retrieve → evaluate → complete / escalate      │
└───────────────────────────────────────────────────────────┘
```

关键边界：

- `GlobalGraph` 决定下一步是否 schedule / clarify / finalize
- `SubtaskGraph` 只负责局部闭环，不直接越权改全局控制流
- Celery 负责异步卸载，不负责替代 `GlobalGraph` 做推进决策

## 8. 人机协作流程图

### 动态中断 `interrupt()`（推荐主线）

```text
正常执行流:
    node_A → node_B → node_C → END

动态中断:
    node_B 内部根据状态判断
        if risk > threshold:
            interrupt(payload)
        resume(Command(resume=value))
```

### interrupt_before（静态节点前断点）

```text
node_A → [暂停] → node_B → END
         │
         └─ 保存 checkpoint
            用户审批 / 修改
            Command(resume=value)
            从 checkpoint 恢复 → node_B
```

### interrupt_after（静态节点后断点）

```text
node_A → node_B → [暂停] → END
                   │
                   └─ 保存 checkpoint（含 node_B 输出）
                      用户审核结果
                      Command(resume=value)
                      恢复 → END
```

当前口径：

- 动态 `interrupt()` 是生产推荐路径
- `interrupt_before` / `interrupt_after` 继续保留为教学与调试示例

## 9. 概念到文件映射表

| 核心概念 | 教程文件 | 模板文件 |
|----------|----------|----------|
| StateGraph 基础 | `01_graph_fundamentals/01-04` | `templates/graph_builder.py` |
| TypedDict / reducer / state-config-context 边界 | `02_state_deep_dive/01-06` | `templates/state_schemas.py` |
| 条件边路由 | `03_edges_and_routing/01-04` | — |
| 工具调用 | `04_tool_calling/01-04` | — |
| Checkpoint 持久化 / schema 演进 / 幂等恢复 | `05_checkpointing/01-07` | `templates/checkpoint_manager.py` |
| 流式输出 / replay / dual channel | `06_streaming/01-07` | `templates/fastapi_graph_app.py` |
| 子图组合 / `Command.PARENT` | `07_subgraph_composition/01-05` | — |
| 人机协作 / 结构化审批 / Clarify 默认项 | `08_human_in_the_loop/01-06` | — |
| 错误处理 / RetryPolicy / CachePolicy | `09_error_and_resilience/01-05` | `templates/safe_node.py` |
| 多 Agent / graph worker / partial reuse | `10_multi_agent/01-08` | `templates/multi_agent_orchestrator.py` |
| 动态并行 | `11_dynamic_and_parallel/01-04` | — |
| 记忆系统 / InjectedStore / Store 生命周期 | `12_memory_and_store/01-07` | `templates/store_manager.py` |
| 函数式 API | `13_functional_api/01-03` | — |
| 测试调试 / resume/replay 测试 | `14_testing_and_debugging/01-05` | — |
| 生产部署 | `15_production_deployment/01-04` | `templates/fastapi_graph_app.py` |
| AgenticRAG / 控制面恢复 / stale fencing | `16_agentic_rag_patterns/01-07` | `templates/celery_graph_bridge.py` |

## 10. Graph API vs Functional API 对比

```text
Graph API（StateGraph）                    Functional API（@entrypoint/@task）
┌──────────────────────────┐              ┌──────────────────────────┐
│  builder = StateGraph()  │              │  @entrypoint(checkpointer)│
│  builder.add_node(...)   │              │  async def workflow(...): │
│  builder.add_edge(...)   │              │      r1 = task_a(...)     │
│  graph = builder.compile()│             │      if condition:        │
│  await graph.ainvoke(...)│              │          r2 = task_b(...) │
└──────────────────────────┘              └──────────────────────────┘
```

| 维度 | Graph API | Functional API |
|------|-----------|----------------|
| 控制流 | 边 + 条件边 | `if` / `for` / `while` |
| 状态管理 | state + reducer | 函数参数 / task 返回值 |
| 可视化 | ✅ Mermaid | ❌ 不支持 |
| 并行执行 | ✅ `Send` 原生支持 | ❌ 需自行组织 |
| 子图嵌套 | ✅ 原生支持 | ❌ 不适合复杂拓扑 |
| 学习曲线 | 略陡 | 较平缓 |
| 适合场景 | 复杂拓扑、多 Agent | 线性流程、轻量 workflow |

当前教程建议：

- 复杂系统优先 Graph API
- Functional API 作为补充能力而不是默认主线
