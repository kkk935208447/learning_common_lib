# LangGraph 架构全景图

## 1. 核心分层架构

```
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
│  Superstep 循环 → 节点调度 → 并行执行 → Channel 合并                  │
│  支持: invoke / stream / ainvoke / astream                          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
             ┌───────────┐ ┌──────────┐ ┌──────────┐
             │  Channel  │ │Checkpoint│ │  Store   │
             │  系统      │ │  持久化   │ │ 长期记忆  │
             └───────────┘ └──────────┘ └──────────┘
```

## 2. Pregel 执行模型详细图

```
                         Superstep N 完整流程
┌─────────────────────────────────────────────────────────────────────┐
│  ① 读取 Channels        ② 确定活跃节点        ③ 并行执行节点         │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      │
│  │ 从 checkpoint │  →   │ 根据入边和    │  →   │  node_A()    │      │
│  │ 恢复 state    │      │ 条件判断哪些  │      │  node_B()    │      │
│  │              │      │ 节点应执行    │      │  (并行)      │      │
│  └──────────────┘      └──────────────┘      └──────┬───────┘      │
│                                                      │              │
│  ⑧ 确定下一步          ⑦ 保存 checkpoint    ⑥ 写入 Channels        │
│  ┌──────────────┐      ┌──────────────┐      ┌──────┴───────┐      │
│  │ 评估条件边    │  ←   │ checkpointer │  ←   │ 通过 reducer  │      │
│  │ 确定下一轮    │      │ .put(state)  │      │ 合并到 state  │      │
│  │ 活跃节点     │      │              │      │              │      │
│  └──────────────┘      └──────────────┘      └──────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

关键点：
- 同一 superstep 内的多个节点并行执行，互不可见彼此的输出
- Reducer 决定状态字段如何合并（追加、覆盖、清除）
- 每个 superstep 结束后保存 checkpoint，确保可恢复性

## 3. Channel 系统详图

```
                        Channel 类型体系
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  LastValue Channel（默认）                                           │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │  语义：后写覆盖（last-write-wins）                         │       │
│  │  用途：普通标量字段（status、next_action、error）           │       │
│  │  行为：节点 A 写 "x"，节点 B 写 "y" → 最终值 = "y"        │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
│  BinaryOperatorAggregate Channel（Annotated reducer）               │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │  语义：自定义归约函数 f(left, right) → merged              │       │
│  │  用途：列表追加、计数器累加、集合合并                        │       │
│  │  示例：                                                    │       │
│  │    Annotated[list, operator.add]     → 列表追加             │       │
│  │    Annotated[list, add_messages]     → 按 ID 去重/更新      │       │
│  │    Annotated[int, lambda a, b: a+b]  → 计数器累加           │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
│  EphemeralValue Channel                                             │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │  语义：superstep 结束后自动清除                             │       │
│  │  用途：临时标记、一次性信号（如 "需要人工审核" 标志）        │       │
│  │  行为：写入 → 当前 superstep 可读 → 下一 superstep 为空    │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

数据流：节点返回 dict → Channel 接收 → reducer 合并 → 更新 state
```

## 4. Checkpoint 流转图

```
  invoke(input, config={"configurable": {"thread_id": "t1"}})
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ CP-0     │ →  │ CP-1     │ →  │ CP-2     │ →  │ CP-3     │
│ (初始)   │    │ (step 1) │    │ (step 2) │    │ (step 3) │
│ input    │    │ +node_A  │    │ +node_B  │    │ +node_C  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                      │                               │
                      ▼ 时间旅行                       ▼ 最新状态
                ┌──────────┐                    graph.get_state(config)
                │ 从 CP-1  │
                │ 分叉新线  │
                └──────────┘

存储后端：
┌──────────────────────────────────────────────────┐
│  MemorySaver     → 开发/测试（进程内，重启丢失）    │
│  SqliteSaver     → 单机持久化                      │
│  AsyncRedisSaver → 生产环境（跨进程、支持 TTL）     │
│  PostgresSaver   → 生产环境（事务安全）             │
└──────────────────────────────────────────────────┘

thread_id 命名约定（AgenticRAG）：
  GlobalGraph:  tenant:{tenant_id}:task:{task_id}
  SubtaskGraph: tenant:{tid}:task:{tid}:plan:{v}:subtask:{code}:exec:{eid}
```

## 5. 流式输出模式对比

```
                    graph.stream() / graph.astream()
                              │
              ┌───────────────┼───────────────┬──────────────┐
              ▼               ▼               ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  values  │   │ updates  │   │  events  │   │ messages │
        │ 完整快照  │   │ 增量更新  │   │ 细粒度   │   │ LLM token│
        └──────────┘   └──────────┘   └──────────┘   └──────────┘
              │               │               │              │
              ▼               ▼               ▼              ▼
        每步输出完整     只输出变化的      on_chain_*     (chunk, meta)
        state 字典      字段 dict        on_llm_*       逐 token 推送
                                         on_tool_*
```

| 模式 | 数据粒度 | 适用场景 | 数据量 |
|------|----------|----------|--------|
| `values` | 完整 state 快照 | 调试、状态监控 | 大 |
| `updates` | 节点级增量 | 前端状态同步 | 中 |
| `events` | 事件级（含子图） | 复杂 UI、可观测性 | 大 |
| `messages` | LLM token 级 | 聊天界面逐字输出 | 小 |
| `custom` | 自定义事件 | 进度通知 | 按需 |

## 6. 多 Agent 模式架构图

```
模式 1: Supervisor（中心调度）
┌─────────────────────────────────────────┐
│              Supervisor                  │
│         ┌──────┼──────┐                 │
│         ▼      ▼      ▼                 │
│     Worker_A Worker_B Worker_C          │
│         │      │      │                 │
│         └──────┼──────┘                 │
│                ▼                         │
│           共享 State                     │
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
│  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐   │
│  │plan │→ │sched│→ │exec │→ │eval │   │
│  └─────┘  └─────┘  └──┬──┘  └─────┘   │
│                        │                 │
│              ┌─────────▼─────────┐       │
│              │  SubtaskGraph     │       │
│              │  （数据平面）       │       │
│              │  retrieve→gen→chk │       │
│              └───────────────────┘       │
└─────────────────────────────────────────┘

模式 5: 黑板模式
┌─────────────────────────────────────────┐
│           Blackboard (共享 State)         │
│  ┌──────────────────────────────────┐   │
│  │ field_A: Agent_1 可写             │   │
│  │ field_B: Agent_2 可写             │   │
│  │ field_C: Agent_3 可写             │   │
│  │ shared:  所有 Agent 可读          │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## 7. AgenticRAG 双图架构详细图
详情见: [AgenticRAG Multi-Agent deepsearch架构](../../案例/用户AgenticRAG检索/AI_Agent指令.md)

```
┌─────────────────── GlobalGraph（控制平面）───────────────────┐
│                                                              │
│  GlobalState:                                                │
│    task_id, tenant_id, plan_version,                         │
│    subtask_codes, step, status, error                        │
│                                                              │
│  ┌──────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │intake │ →  │ planner  │ →  │scheduler │ →  │evaluator │  │
│  └──────┘    └──────────┘    └────┬─────┘    └────┬─────┘  │
│                                    │               │         │
│                    step_gate_router (五路分发)       │         │
│              ┌────┬────┬────┬────┐                  │         │
│              ▼    ▼    ▼    ▼    ▼                  │         │
│           sched replan eval final fallback          │         │
│              │                                      │         │
│              ▼                                      │         │
│  ┌───────────────────── SubtaskGraph ──────────────┐│         │
│  │                                                  ││         │
│  │  SubtaskState:                                   ││         │
│  │    subtask_code, query, documents,               ││         │
│  │    iteration, max_iterations, fingerprint        ││         │
│  │                                                  ││         │
│  │  retrieve → generate → check_quality             ││         │
│  │     ↑                       │                    ││         │
│  │     └── loop_guard_router ──┘                    ││         │
│  │     (max_iter + fingerprint 检测)                ││         │
│  └──────────────────────────────────────────────────┘│         │
│                                                      │         │
│              ←── 结果回写 GlobalState ───────────────┘         │
└──────────────────────────────────────────────────────────────┘
```

## 8. 人机协作流程图

```
                    正常执行流
    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
    │node_A│ →  │node_B│ →  │node_C│ →  │ END  │
    └──────┘    └──────┘    └──────┘    └──────┘

interrupt_before（节点前暂停）:
    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
    │node_A│ →  │⏸ 暂停│ →  │node_B│ →  │ END  │
    └──────┘    └──┬───┘    └──────┘    └──────┘
                   │ 保存 checkpoint
                   ▼
              用户审批/修改
                   │
                   ▼ Command(resume=value)
              从 checkpoint 恢复 → node_B 继续

interrupt_after（节点后暂停）:
    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
    │node_A│ →  │node_B│ →  │⏸ 暂停│ →  │ END  │
    └──────┘    └──────┘    └──┬───┘    └──────┘
                               │ 保存 checkpoint（含 node_B 输出）
                               ▼
                          用户审核结果
                               │
                               ▼ Command(resume=value)
                          恢复 → END

动态中断 interrupt()（条件性暂停）:
    async def risky_node(state):
        if state["risk_score"] > 0.8:
            answer = interrupt("高风险操作，是否继续？")
            if answer != "yes":
                return {"status": "cancelled"}
        return {"status": "executed"}
```

## 9. 概念到文件映射表

| 核心概念 | 教程文件 | 模板文件 |
|----------|----------|----------|
| StateGraph 基础 | `01_graph_fundamentals/01-04` | `templates/graph_builder.py` |
| TypedDict 状态 | `02_state_deep_dive/01-05` | `templates/state_schemas.py` |
| 条件边路由 | `03_edges_and_routing/01-04` | — |
| 工具调用 | `04_tool_calling/01-04` | — |
| Checkpoint 持久化 | `05_checkpointing/01-04` | `templates/checkpoint_manager.py` |
| 流式输出 | `06_streaming/01-04` | `templates/fastapi_graph_app.py` |
| 子图组合 | `07_subgraph_composition/01-04` | — |
| 人机协作 | `08_human_in_the_loop/01-04` | — |
| 错误处理 | `09_error_and_resilience/01-04` | `templates/safe_node.py` |
| 多 Agent | `10_multi_agent/01-05` | `templates/multi_agent_orchestrator.py` |
| 动态并行 | `11_dynamic_and_parallel/01-04` | — |
| 记忆系统 | `12_memory_and_store/01-03` | — |
| 函数式 API | `13_functional_api/01-03` | — |
| 测试调试 | `14_testing_and_debugging/01-04` | — |
| 生产部署 | `15_production_deployment/01-04` | `templates/fastapi_graph_app.py` |
| AgenticRAG | `16_agentic_rag_patterns/01-04` | `templates/celery_graph_bridge.py` |

## 10. Graph API vs Functional API 对比

```
Graph API（StateGraph）                    Functional API（@entrypoint/@task）
┌──────────────────────────┐              ┌──────────────────────────┐
│  builder = StateGraph()  │              │  @entrypoint(checkpointer)│
│  builder.add_node(...)   │              │  def workflow(inputs):    │
│  builder.add_edge(...)   │              │      r1 = task_a(inputs)  │
│  graph = builder.compile()│             │      if condition:        │
│  graph.invoke(...)       │              │          r2 = task_b(r1)  │
└──────────────────────────┘              └──────────────────────────┘

适用场景对比：
┌──────────────┬──────────────────┬──────────────────┐
│ 维度          │ Graph API        │ Functional API   │
├──────────────┼──────────────────┼──────────────────┤
│ 控制流        │ 边 + 条件边       │ if/for/while     │
│ 状态管理      │ Channel + Reducer │ 函数参数          │
│ 可视化        │ ✅ Mermaid        │ ❌ 不支持         │
│ 并行执行      │ ✅ 自动并行       │ ❌ 需手动         │
│ 子图嵌套      │ ✅ 原生支持       │ ❌ 不支持         │
│ 人机协作      │ ✅ interrupt      │ ✅ interrupt      │
│ 学习曲线      │ 较陡             │ 平缓              │
│ 适合场景      │ 复杂拓扑/多Agent  │ 简单线性流程      │
└──────────────┴──────────────────┴──────────────────┘
```
