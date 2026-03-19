# LangGraph 学习路线图

## 前置步骤：验证环境

```bash
# 确保 Redis 已启动且密码正确（检查点持久化、AgenticRAG 需要）
docker exec <redis容器名> redis-cli -a 123456 ping  # → PONG
python -c "import redis; print(redis.Redis(host='localhost', port=6379, password='123456').ping())"

# 确保依赖已安装
uv sync
# 或
pip install langgraph langgraph-checkpoint-redis langchain-core langchain-community redis "celery[redis]" fastapi uvicorn
```

## 阶段一：图基础（第 1-3 章）

> 目标：理解 LangGraph 核心模型 — Graph、State、Node、Edge、Channel

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 1 | `examples/01_graph_fundamentals/01_minimal_graph.py` | 最小两节点图、START/END 虚拟节点 | 先跑通最简单的图 |
| 2 | `examples/01_graph_fundamentals/02_multi_node_chain.py` | 三节点链式、partial state 返回 | 理解状态传递机制 |
| 3 | `examples/01_graph_fundamentals/03_execution_model.py` | Pregel superstep 执行模型 | 理解底层执行原理 |
| 4 | `examples/01_graph_fundamentals/04_graph_visualization.py` | Mermaid 可视化 | 调试时快速验证拓扑 |
| 5 | `examples/02_state_deep_dive/01_typed_dict_state.py` | TypedDict 状态定义、total=True vs False | 状态是 LangGraph 的核心 |
| 6 | `examples/02_state_deep_dive/02_annotated_reducers.py` | Annotated reducer 追加语义 | 理解状态合并策略 |
| 7 | `examples/02_state_deep_dive/03_message_state.py` | MessagesState 预置 schema | 对话场景的标准状态 |
| 8 | `examples/02_state_deep_dive/04_pydantic_state.py` | Pydantic 状态验证 | 运行时类型安全 |
| 9 | `examples/02_state_deep_dive/05_state_channels.py` | Channel 类型深入 | 理解底层状态机制 |
| 10 | `examples/03_edges_and_routing/01_normal_edges.py` | 普通边、入口边、END 边 | 边的三种基本类型 |
| 11 | `examples/03_edges_and_routing/02_conditional_edges.py` | 条件边、路由映射 dict | 动态路由是核心能力 |
| 12 | `examples/03_edges_and_routing/03_multi_way_router.py` | 五路路由器（step_gate_router） | 模拟 AgenticRAG 五路分发 |
| 13 | `examples/03_edges_and_routing/04_loop_with_guard.py` | 循环边 + 迭代守卫 + fingerprint 检测 | 防止无限循环 |

> 每个示例直接运行：`python examples/01_graph_fundamentals/01_minimal_graph.py`

## 阶段二：工具与持久化（第 4-6 章）

> 目标：掌握 LLM 工具调用、状态持久化、流式输出三大生产必备能力

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 14 | `examples/04_tool_calling/01_tool_node_basics.py` | @tool + bind_tools + ToolNode | 工具调用是 Agent 的核心能力 |
| 15 | `examples/04_tool_calling/02_custom_tool_execution.py` | 手动解析 tool_calls、ToolMessage 构造 | 理解底层机制才能排障 |
| 16 | `examples/04_tool_calling/03_tool_error_handling.py` | handle_tool_errors、LLM 自我纠正 | 工具失败是常态，必须处理 |
| 17 | `examples/04_tool_calling/04_react_agent_pattern.py` | 完整 ReAct Agent 循环 | 最经典的 Agent 模式 |
| 18 | `examples/05_checkpointing/01_memory_saver.py` | 内存 checkpointer、thread_id | 持久化入门 |
| 19 | `examples/05_checkpointing/02_conversation_threads.py` | 多线程对话、独立状态 | thread_id 隔离是多租户基础 |
| 20 | `examples/05_checkpointing/03_time_travel.py` | get_state_history、从历史点分叉 | 调试和回溯的利器 |
| 21 | `examples/05_checkpointing/04_redis_checkpointer.py` | AsyncRedisSaver、ResilientCheckpointer | 生产级持久化 |
| 22 | `examples/06_streaming/01_stream_values.py` | values 模式：完整状态快照 | 调试和状态监控 |
| 23 | `examples/06_streaming/02_stream_updates.py` | updates 模式：增量更新 | 前端状态同步 |
| 24 | `examples/06_streaming/03_stream_events.py` | events 模式：细粒度事件流 | 复杂 UI 交互 |
| 25 | `examples/06_streaming/04_token_streaming.py` | token 级流式 + SSE | 聊天界面逐字输出 |

> 05 章第 4 节需要 Redis；06 章的 03/04 是异步示例。

## 阶段三：架构级能力（第 7-9 章）

> 目标：掌握子图组合、人机协作、错误处理——从单 Agent 到系统级设计

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 26 | `examples/07_subgraph_composition/01_subgraph_as_node.py` | 子图作为节点嵌入父图 | 图的模块化复用 |
| 27 | `examples/07_subgraph_composition/02_state_mapping.py` | 父子图状态 schema 映射 | 解决状态不一致问题 |
| 28 | `examples/07_subgraph_composition/03_command_handoff.py` | Command 原语跨图切换 | Agent 间任务交接 |
| 29 | `examples/07_subgraph_composition/04_nested_dual_graph.py` | 双图架构（Global + Subtask） | 直接模拟 AgenticRAG 双图 |
| 30 | `examples/08_human_in_the_loop/01_interrupt_before.py` | interrupt_before 节点前暂停 | 危险操作前人工审批 |
| 31 | `examples/08_human_in_the_loop/02_interrupt_after.py` | interrupt_after 节点后暂停 | 结果审核再继续 |
| 32 | `examples/08_human_in_the_loop/03_dynamic_breakpoints.py` | NodeInterrupt / interrupt() 动态中断 | 条件性暂停（高风险时才中断） |
| 33 | `examples/08_human_in_the_loop/04_approval_workflow.py` | 完整审批流 + Clarify 模式 | 企业级人机协作 |
| 34 | `examples/09_error_and_resilience/01_safe_node_wrapper.py` | safe_node 装饰器（超时+异常分级） | 节点级错误隔离，参考 AgenticRAG |
| 35 | `examples/09_error_and_resilience/02_retry_with_backoff.py` | 条件边重试 + 指数退避 | 区分 TRANSIENT/PERMANENT/DEGRADABLE |
| 36 | `examples/09_error_and_resilience/03_fallback_chain.py` | 多级降级：主路径→备选→兜底 | 非关键路径的优雅降级 |
| 37 | `examples/09_error_and_resilience/04_escalation_protocol.py` | 子任务升级到全局循环 | 5 种升级触发条件 |

> 08 章依赖 05 章的 checkpointer；09 章的 safe_node 模式可直接复用到生产。

## 阶段四：多 Agent 与高级特性（第 10-13 章）

> 目标：掌握多 Agent 编排、动态并行、记忆系统、函数式 API

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 38 | `examples/10_multi_agent/01_supervisor_pattern.py` | Supervisor 中心调度 | 最常用的多 Agent 模式 |
| 39 | `examples/10_multi_agent/02_swarm_pattern.py` | Swarm 去中心化协作 | Agent 自主 handoff 切换 |
| 40 | `examples/10_multi_agent/03_plan_execute_replan.py` | Plan-Execute-Replan 循环 | 模拟 AgenticRAG 全局循环 |
| 41 | `examples/10_multi_agent/04_hierarchical_agents.py` | 两层 Agent：全局调度+子任务执行 | 大规模 Agent 组织 |
| 42 | `examples/10_multi_agent/05_blackboard_pattern.py` | 黑板模式：共享状态协调 | 松耦合多 Agent 协作 |
| 43 | `examples/11_dynamic_and_parallel/01_send_api_fanout.py` | Send API 动态 fan-out | 运行时决定并行数量 |
| 44 | `examples/11_dynamic_and_parallel/02_send_vs_command.py` | Send vs Command 对比 | Send=并行 fan-out，Command=单路由 |
| 45 | `examples/11_dynamic_and_parallel/03_configurable_graph.py` | 运行时配置切换图行为 | 同一图不同配置变体 |
| 46 | `examples/11_dynamic_and_parallel/04_map_reduce_aggregation.py` | 并行执行后聚合结果 | map-reduce 模式 |
| 47 | `examples/12_memory_and_store/01_short_term_memory.py` | Graph State 作为短期记忆 | 消息窗口管理、摘要压缩 |
| 48 | `examples/12_memory_and_store/02_long_term_store.py` | Store 跨线程长期记忆 | namespace 隔离、key-value 存储 |
| 49 | `examples/12_memory_and_store/03_multi_layer_memory.py` | 五层记忆架构（L1-L5） | 短期+长期+外部协同 |
| 50 | `examples/13_functional_api/01_entrypoint_basics.py` | @entrypoint 工作流入口 | 原生 if/for 控制流 |
| 51 | `examples/13_functional_api/02_task_decorator.py` | @task 可检查点子任务 | 自动 checkpoint |
| 52 | `examples/13_functional_api/03_functional_vs_graph.py` | Functional vs Graph API 并排对比 | 何时用哪种 API |

> 10 章依赖 03+07 章；11 章的 Send API 是 LangGraph 独有能力；12 章依赖 05 章。

## 阶段五：工程实战（第 14-16 章）

> 目标：掌握测试、部署、AgenticRAG 实战——从能用到能上线

| 顺序 | 文件 | 学什么 | 为什么在这里 |
|------|------|--------|-------------|
| 53 | `examples/14_testing_and_debugging/01_unit_test_nodes.py` | 节点函数单元测试 | 节点是纯函数，最小测试粒度 |
| 54 | `examples/14_testing_and_debugging/02_integration_test_graph.py` | 完整图集成测试 | 端到端验证图行为 |
| 55 | `examples/14_testing_and_debugging/03_mock_llm.py` | FakeListChatModel Mock | 无需 API key 的确定性测试 |
| 56 | `examples/14_testing_and_debugging/04_debug_visualization.py` | get_state + Mermaid 调试 | 运行时状态追踪 |
| 57 | `examples/15_production_deployment/01_fastapi_sse_integration.py` | FastAPI + SSE 流式端点 | Web 服务部署 |
| 58 | `examples/15_production_deployment/02_observability.py` | 结构化日志 + 五级 trace ID | 生产可观测性 |
| 59 | `examples/15_production_deployment/03_double_texting.py` | 4 种重复请求处理策略 | 并发安全 |
| 60 | `examples/15_production_deployment/04_graceful_shutdown.py` | signal handler + checkpoint 保存 | 零丢失停机 |
| 61 | `examples/16_agentic_rag_patterns/01_global_graph_skeleton.py` | GlobalState + step_gate_router | AgenticRAG 顶层编排 |
| 62 | `examples/16_agentic_rag_patterns/02_subtask_graph_skeleton.py` | SubtaskState + loop_guard_router | 检索/生成子图 |
| 63 | `examples/16_agentic_rag_patterns/03_celery_bridge.py` | resume_orchestrator 模式 | 异步任务卸载（禁止 .get()） |
| 64 | `examples/16_agentic_rag_patterns/04_dag_dispatch_pattern.py` | compute_ready_codes + dispatch | 多步检索 DAG 编排 |

> 16 章是全教程的综合实战，建议前 15 章全部完成后再进入。直接对应 `案例/用户AgenticRAG检索/技术拆解.md`。

## 阶段六：企业模板

> 目标：直接复用到生产项目

| 顺序 | 文件 | 用途 |
|------|------|------|
| 65 | `templates/state_schemas.py` | 可复用状态 schema（BaseState/AgentState/MessageAgentState） |
| 66 | `templates/safe_node.py` | 节点错误处理中间件（超时 + 异常分级 + 结构化日志） |
| 67 | `templates/graph_builder.py` | 生产级图构建工厂（统一节点注册 + safe_node 包装） |
| 68 | `templates/checkpoint_manager.py` | Checkpoint 管理器（Redis/内存自动切换 + ResilientCheckpointer） |
| 69 | `templates/multi_agent_orchestrator.py` | 多 Agent 编排骨架（Supervisor + Plan-Execute-Replan） |
| 70 | `templates/celery_graph_bridge.py` | LangGraph + Celery 桥接（dispatch + resume_orchestrator） |
| 71 | `templates/fastapi_graph_app.py` | FastAPI 集成（SSE 流式 + lifespan + 健康检查） |

> 模板代码可直接 copy 到项目中使用，每个模板底部有 `_demo()` 函数可独立运行验证。

## 依赖关系图

```
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

1. 按顺序逐文件运行：先读注释理解设计意图，再运行观察输出
2. 每章结束后回顾 `architecture_map.md` 对应层
3. 遇到疑问查 `pitfalls.md` 和 `best_practices.md`
4. 修改参数验证理解（如改 max_iterations、切换 stream mode、换 thread_id）
5. 最后用 `smoke/run_all_examples.py` 验证全部通过
