# LangGraph 学习路线图

本路线图恢复了原有阶段划分、依赖关系和章节说明，同时统一校正为 **async-first** 教学主线。

## 前置步骤：验证环境

```bash
# 确保依赖已安装
uv sync

# 如需显式安装 Redis checkpoint 集成
uv add langgraph-checkpoint-redis

# 确保 Redis 已启动且密码正确（checkpoint / store / Celery 需要）
# 推荐先用 Python 方式验证
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 如本机安装了 redis-cli，也可以补充验证
docker exec <redis容器名> redis-cli -a 123456 ping  # → PONG
```

补充说明：

- `langgraph-checkpoint-redis` 需要支持 RediSearch / Redis Stack 的 Redis 实例
- 普通 Redis 能连通，不代表 Redis checkpoint / RedisStore 一定能真正初始化成功
- Store 默认必须使用 `db=0`，否则可能报 `Cannot create index on db != 0`
- 集成示例与 smoke 默认启用严格模式，只要降级到内存 backend 就算失败

## 阶段一：图基础（第 1-3 章）

> 目标：理解 LangGraph 核心模型：Graph、State、Node、Edge、Reducer、Superstep

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 1 | `examples/01_graph_fundamentals/01_minimal_graph.py` | 最小两节点图、START/END 虚拟节点 | 唯一保留的同步最小对照 |
| 2 | `examples/01_graph_fundamentals/02_multi_node_chain.py` | 三节点链式、partial state 返回 | 最小同步链式对照 |
| 3 | `examples/01_graph_fundamentals/03_execution_model.py` | Pregel superstep 执行模型 | 从这里开始切入 async-first |
| 4 | `examples/01_graph_fundamentals/04_graph_visualization.py` | Mermaid 可视化 | 用图结构辅助理解拓扑 |
| 5 | `examples/02_state_deep_dive/01_typed_dict_state.py` | TypedDict 状态定义、total=True vs False | 状态是 LangGraph 的核心 |
| 6 | `examples/02_state_deep_dive/02_annotated_reducers.py` | Annotated reducer 追加语义 | 理解状态合并策略 |
| 7 | `examples/02_state_deep_dive/03_message_state.py` | MessagesState 预置 schema | 对话场景标准状态 |
| 8 | `examples/02_state_deep_dive/04_pydantic_state.py` | Pydantic 运行时校验 | 复杂状态建模 |
| 9 | `examples/02_state_deep_dive/05_state_channels.py` | Channel 类型深入 | 理解底层状态机制 |
| 10 | `examples/02_state_deep_dive/06_state_vs_config_vs_context.py` | state / config / runtime context 边界 | 避免把 thread_id/trace_id 塞进业务 state |
| 11 | `examples/03_edges_and_routing/01_normal_edges.py` | 普通边、入口边、END 边 | 边的三种基本类型 |
| 12 | `examples/03_edges_and_routing/02_conditional_edges.py` | 条件边、路由映射 dict | 动态路由是核心能力 |
| 13 | `examples/03_edges_and_routing/03_multi_way_router.py` | 五路路由器 | 模拟 AgenticRAG 分流 |
| 14 | `examples/03_edges_and_routing/04_loop_with_guard.py` | 循环边 + 迭代守卫 + fingerprint 检测 | 防止无限循环 |

建议：

- 第 1、2 个例子理解“最小图”
- 从第 3 个例子开始，按 async-first 方式阅读和运行

## 阶段二：工具与持久化（第 4-6 章）

> 目标：掌握 LLM 工具调用、状态持久化、流式输出三大生产必备能力

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 14 | `examples/04_tool_calling/01_tool_node_basics.py` | @tool + ToolNode 入图 | 工具调用是 Agent 的核心能力 |
| 15 | `examples/04_tool_calling/02_custom_tool_execution.py` | 手动解析 tool_calls、ToolMessage 构造 | 理解底层机制才能排障 |
| 16 | `examples/04_tool_calling/03_tool_error_handling.py` | handle_tool_errors、LLM 自我纠正 | 工具失败是常态 |
| 17 | `examples/04_tool_calling/04_react_agent_pattern.py` | 完整 ReAct Agent 循环 | 最经典 Agent 模式 |
| 18 | `examples/05_checkpointing/01_memory_saver.py` | 内存 checkpointer、thread_id | 持久化入门 |
| 19 | `examples/05_checkpointing/02_conversation_threads.py` | 多线程对话、独立状态 | thread_id 隔离是多租户基础 |
| 20 | `examples/05_checkpointing/03_time_travel.py` | get_state_history、从历史点分叉 | 调试和回溯的利器 |
| 21 | `examples/05_checkpointing/04_redis_checkpointer.py` | AsyncRedisSaver、降级策略 | 生产级持久化边界 |
| 22 | `examples/05_checkpointing/05_checkpoint_schema_evolution.py` | state schema 演进兼容 | 避免旧 checkpoint 在升级后炸掉 |
| 23 | `examples/05_checkpointing/06_subgraph_thread_strategy.py` | Global/Subtask thread_id 规范 | 父图与子图不能串 checkpoint |
| 24 | `examples/05_checkpointing/07_idempotent_resume_side_effects.py` | 恢复后的副作用幂等 | execution_id 是关键防线 |
| 25 | `examples/06_streaming/01_stream_values.py` | `values`：完整状态快照 | 调试和状态监控 |
| 26 | `examples/06_streaming/02_stream_updates.py` | `updates`：节点级增量 | 前端状态同步 |
| 27 | `examples/06_streaming/03_stream_events.py` | `astream_events()`：细粒度事件流 | trace / observability |
| 28 | `examples/06_streaming/04_token_streaming.py` | `messages`：token 级流式 + SSE | 聊天界面逐字输出 |
| 29 | `examples/06_streaming/05_sse_replay_and_heartbeat.py` | Last-Event-ID + heartbeat | 真实 SSE 主反馈语义 |
| 30 | `examples/06_streaming/06_dual_channel_streaming.py` | token / progress 双通道 | 结构化事件不要和 token 混流 |
| 31 | `examples/06_streaming/07_store_backed_event_replay.py` | store-backed event replay | token 流不能做 durable replay |

这一阶段的关键口径：

- `ToolNode` 主要应作为图节点使用
- checkpoint 与 store 不同
- 流式主线是 `astream(..., stream_mode=...)`
- `astream_events()` 是事件观测，不是默认聊天 SSE 接口

## 阶段三：架构级能力（第 7-9 章）

> 目标：掌握子图组合、人机协作、错误处理，从单 Agent 走向系统设计

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 32 | `examples/07_subgraph_composition/01_subgraph_as_node.py` | 子图作为节点嵌入父图 | 图的模块化复用 |
| 33 | `examples/07_subgraph_composition/02_state_mapping.py` | 父子图状态 schema 映射 | 解决状态不一致问题 |
| 34 | `examples/07_subgraph_composition/03_command_handoff.py` | Command 原语跨图切换 | Agent 间 handoff |
| 35 | `examples/07_subgraph_composition/04_nested_dual_graph.py` | 双图架构（Global + Subtask） | 直接模拟 AgenticRAG 双图 |
| 36 | `examples/07_subgraph_composition/05_command_parent_handoff.py` | `Command.PARENT` 控制权回收 | 子图如何把决策交回父图 |
| 37 | `examples/08_human_in_the_loop/03_dynamic_breakpoints.py` | 动态 `interrupt()` | 生产主线的人机协作 |
| 38 | `examples/08_human_in_the_loop/04_approval_workflow.py` | toy baseline 审批流 | 先理解 interrupt，再看结构化版 |
| 39 | `examples/08_human_in_the_loop/05_structured_approval_contract.py` | 结构化审批恢复 | 企业审批不该用裸字符串 |
| 40 | `examples/08_human_in_the_loop/06_clarify_with_timeout_default.py` | Clarify 默认项恢复 | 超时默认项必须显式可审计 |
| 41 | `examples/08_human_in_the_loop/01_interrupt_before.py` | interrupt_before | 静态断点补充 |
| 42 | `examples/08_human_in_the_loop/02_interrupt_after.py` | interrupt_after | 静态断点补充 |
| 43 | `examples/09_error_and_resilience/01_safe_node_wrapper.py` | safe_node 装饰器 | 节点级错误隔离 |
| 44 | `examples/09_error_and_resilience/02_retry_with_backoff.py` | 条件边重试 + 指数退避 | TRANSIENT/PERMANENT/DEGRADABLE |
| 45 | `examples/09_error_and_resilience/03_fallback_chain.py` | 多级降级 | 非关键路径的优雅降级 |
| 46 | `examples/09_error_and_resilience/04_escalation_protocol.py` | 子任务升级到全局循环 | 结构化升级协议 |
| 47 | `examples/09_error_and_resilience/05_retry_policy_and_cache_policy.py` | 内置 retry/cache policy | 不只会手写 retry/fallback |

重点提醒：

- 08 章依赖 05 章的 checkpoint 理解
- 动态中断优先，静态断点辅助
- 09 章的模式可直接迁移到生产模板

## 阶段四：多 Agent 与高级特性（第 10-13 章）

> 目标：掌握多 Agent 编排、动态并行、记忆系统、函数式 API

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 48 | `examples/10_multi_agent/01_supervisor_pattern.py` | toy baseline Supervisor | 先理解控制平面概念 |
| 49 | `examples/10_multi_agent/02_swarm_pattern.py` | Swarm 去中心化协作 | Agent 自主 handoff |
| 50 | `examples/10_multi_agent/03_plan_execute_replan.py` | toy baseline Plan-Execute-Replan | 先理解循环形状 |
| 51 | `examples/10_multi_agent/04_hierarchical_agents.py` | toy baseline 双图 | 先理解父图调子图 |
| 52 | `examples/10_multi_agent/05_blackboard_pattern.py` | 黑板模式 | 共享状态协调 |
| 53 | `examples/10_multi_agent/06_supervisor_with_subgraphs.py` | 真实版 graph worker | 子 agent 也是图 |
| 54 | `examples/10_multi_agent/07_replan_with_fingerprint.py` | 结构化 planner + fingerprint | replan 不能只靠 iteration |
| 55 | `examples/10_multi_agent/08_partial_plan_reuse.py` | 部分结果复用 | replan 不是推倒重来 |
| 56 | `examples/11_dynamic_and_parallel/01_send_api_fanout.py` | Send API 动态 fan-out | 运行时决定并行数量 |
| 54 | `examples/11_dynamic_and_parallel/02_send_vs_command.py` | Send vs Command 对比 | 一对多 vs 一对一 |
| 55 | `examples/11_dynamic_and_parallel/03_configurable_graph.py` | configurable | 同图多配置变体 |
| 56 | `examples/11_dynamic_and_parallel/04_map_reduce_aggregation.py` | 并行执行后聚合结果 | map-reduce 模式 |
| 60 | `examples/12_memory_and_store/01_short_term_memory.py` | Graph State 作为短期记忆 | 消息窗口管理、摘要压缩 |
| 61 | `examples/12_memory_and_store/02_long_term_store.py` | Store 跨线程长期记忆 | namespace 隔离、KV 存储 |
| 62 | `examples/12_memory_and_store/03_multi_layer_memory.py` | 五层记忆架构（L1-L5） | 短期+长期+外部协同 |
| 63 | `examples/12_memory_and_store/04_state_vs_store_boundary.py` | state/store 边界 | 大对象不要进 checkpoint |
| 64 | `examples/12_memory_and_store/05_store_namespace_and_recall.py` | namespace 设计 | 租户与用户隔离 |
| 65 | `examples/12_memory_and_store/06_tool_with_injected_store.py` | InjectedStore/InjectedState | tool 的系统参数注入 |
| 66 | `examples/12_memory_and_store/07_store_lifecycle_management.py` | Store 生命周期 | 覆盖、删除、冷数据清理 |
| 67 | `examples/13_functional_api/01_entrypoint_basics.py` | @entrypoint 工作流入口 | 原生 if/for 控制流 |
| 68 | `examples/13_functional_api/02_task_decorator.py` | @task 可检查点子任务 | 自动 checkpoint |
| 69 | `examples/13_functional_api/03_functional_vs_graph.py` | Functional vs Graph API 并排对比 | 何时用哪种 API |

这一阶段最重要的边界：

- `Send` 只能在路由 fan-out 中使用
- `Command` 适合 handoff / resume
- checkpoint 和 store 不是同一层能力
- Functional API 适合线性 workflow，不适合复杂可视化拓扑

## 阶段五：工程实战（第 14-16 章）

> 目标：掌握测试、部署、AgenticRAG 实战，从能用走到能上线

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 70 | `examples/14_testing_and_debugging/01_unit_test_nodes.py` | 节点函数单元测试 | 节点是纯函数，最小测试粒度 |
| 71 | `examples/14_testing_and_debugging/02_integration_test_graph.py` | 完整图集成测试 | 端到端验证图行为 |
| 72 | `examples/14_testing_and_debugging/03_mock_llm.py` | fake tool call / 结构化输出 / resume | 更接近真实测试矩阵 |
| 73 | `examples/14_testing_and_debugging/04_debug_visualization.py` | state + Mermaid 调试 | 运行时状态追踪 |
| 74 | `examples/14_testing_and_debugging/05_resume_and_replay_tests.py` | resume/replay/stale guard | 恢复链路回归测试 |
| 75 | `examples/15_production_deployment/01_fastapi_sse_integration.py` | FastAPI + SSE | heartbeat / replay / Last-Event-ID / store-backed events |
| 76 | `examples/15_production_deployment/02_observability.py` | 结构化日志 + trace ID | async-safe 可观测性 |
| 77 | `examples/15_production_deployment/03_double_texting.py` | 同线程等待态重复请求 | reject/enqueue/interrupt/idempotency |
| 78 | `examples/15_production_deployment/04_graceful_shutdown.py` | signal handler + checkpoint | 零丢失停机 |
| 79 | `examples/16_agentic_rag_patterns/01_global_graph_skeleton.py` | GlobalState + Clarify/Subtask 等待链路 | AgenticRAG 顶层编排 |
| 80 | `examples/16_agentic_rag_patterns/02_subtask_graph_skeleton.py` | SubtaskState + WorkerResultEnvelope | 检索/生成子图 |
| 81 | `examples/16_agentic_rag_patterns/03_celery_bridge.py` | dispatch + waiting + accepted/stale + duplicate resume | 异步任务卸载 |
| 82 | `examples/16_agentic_rag_patterns/04_dag_dispatch_pattern.py` | READY batch dispatch | 多步检索 DAG 编排 |
| 83 | `examples/16_agentic_rag_patterns/05_control_plane_vs_runtime_state.py` | 控制面 vs runtime state | checkpoint 不是业务真理源 |
| 84 | `examples/16_agentic_rag_patterns/06_resume_orchestrator_contract.py` | result accepted -> resume | 薄恢复器契约 |
| 85 | `examples/16_agentic_rag_patterns/07_stale_result_fencing.py` | stale result fencing | execution_id 防旧结果污染 |

> 16 章是全教程的综合实战，建议前 15 章全部完成后再进入。直接对应 `案例/用户AgenticRAG检索/技术拆解.md`。

## 阶段六：企业模板

> 目标：直接复用到生产项目

| 顺序 | 文件 | 用途 |
|------|------|------|
| 65 | `templates/state_schemas.py` | 可复用状态 schema |
| 66 | `templates/safe_node.py` | 节点错误处理中间件 |
| 67 | `templates/graph_builder.py` | 生产级图构建工厂 |
| 68 | `templates/runtime_settings.py` | Redis-first 运行时配置 |
| 69 | `templates/checkpoint_manager.py` | Redis-first Checkpoint 管理器 |
| 70 | `templates/store_manager.py` | Redis-first Store 管理器 |
| 71 | `templates/multi_agent_orchestrator.py` | 多 Agent 编排骨架 |
| 72 | `templates/celery_graph_bridge.py` | LangGraph + Celery 桥接 |
| 73 | `templates/fastapi_graph_app.py` | FastAPI 集成 |

模板代码面向“复用模式”，不是最小教学路径；建议在完成前五个阶段后再进入。

## 依赖关系图

```text
01 ──→ 02 ──→ 03 ──→ 04
 │      │      │
 │      ├──→ 05 ──→ 06
 │      │      │
 │      │      ├──→ 08 (Human-in-the-Loop)
 │      │      └──→ 12 (Memory & Store)
 │      │
 └──→ 03 ──→ 07 ──→ 10 (Multi-Agent)
              │      └──→ 11 (Dynamic & Parallel)
              │
        09 (Error & Resilience, 需 01-03)
        13 (Functional API, 需 01-03)
        14 (Testing, 需 01-06)
        15 (Production, 需 05+06+09)
        16 (AgenticRAG, 需全部)
```

## 建议学习方式

1. 按顺序逐文件运行：先看注释和目标，再观察输出
2. 每章结束后回顾 `architecture_map.md` 对应层
3. 遇到疑问查 `pitfalls.md` 和 `best_practices.md`
4. 修改参数验证理解，例如：
   - 改 `max_iterations`
   - 切换 `stream_mode`
   - 更换 `thread_id`
   - 调整 `Send` fan-out 数量
   - 改 `execution_id` 看 stale fencing 是否生效
   - 改 `Last-Event-ID` 看 SSE replay 是否只回放未消费事件
5. 最后用 `smoke/run_all_examples.py` 验证全部通过

## Async-First 阅读建议

如果你是第一次接触 LangGraph：

1. 先跑 `01_minimal_graph.py` 和 `02_multi_node_chain.py`
2. 从 `03_execution_model.py` 开始切换 async-first 心智
3. 后续所有示例都优先观察：
   - `async def main()`
   - `await app.ainvoke(...)`
   - `async for ... in app.astream(...)`

如果你是为了本仓库的 AgenticRAG 实现而学：

1. 先跑 `01`、`03`、`05`、`08`、`10`、`11`
2. 再看 `16_agentic_rag_patterns`
3. 同时对照 `案例/用户AgenticRAG检索/技术拆解.md`
