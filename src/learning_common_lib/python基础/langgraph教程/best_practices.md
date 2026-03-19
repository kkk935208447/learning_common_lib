# LangGraph 最佳实践 (Best Practices)

## 1. 状态设计

- 最小化状态：只存必要字段，大对象用引用（ID/URL）而非内联
- 不可变更新：节点返回新 dict，不直接修改 state
- TypedDict 用 `total=False` 标记可选字段，避免初始化时缺字段报错
- Reducer 选择：消息列表用 `add_messages`，普通列表用 `operator.add`，计数器用自定义 lambda
- 状态字段命名约定：`next_action` 驱动路由、`error` 记录异常、`iteration` 控制循环
  ```python
  # 推荐：引用 + 最小化 + 明确语义
  class GoodState(TypedDict, total=False):
      document_ids: list[str]                          # 只存 ID，不存完整文档
      messages: Annotated[list, add_messages]           # 消息用 add_messages reducer
      iteration: int                                    # 循环计数
      error: str | None                                 # 统一错误字段
      next_action: str                                  # 路由控制字段

  # 避免：大对象内联
  class BadState(TypedDict):
      full_documents: list[dict]  # 每个文档几 KB，10 轮迭代 checkpoint 膨胀到几十 MB
  ```
- TypedDict vs Pydantic 选择：TypedDict 轻量无运行时开销，Pydantic 提供运行时验证；内部状态用 TypedDict，外部输入用 Pydantic

## 2. 节点设计

- 纯函数：节点只依赖 state 输入，不依赖外部可变状态
- safe_node 包装：生产环境必须包装，提供超时和异常兜底
- 单一职责：一个节点做一件事（检索、评估、生成分开）
- 幂等性：同样的输入产生同样的输出（便于 checkpoint 恢复后重试）
- 节点超时按类型设置：intake=5s, planner=15s, retriever=10s, evaluator=10s
- 异步优先：生产环境用 `async def` 节点，避免阻塞事件循环
  ```python
  @safe_node(node_name="retriever", timeout_s=10)
  async def retrieve(state: dict) -> dict:
      docs = await search(state["query"])
      return {"document_ids": [d.id for d in docs]}
  ```

## 3. 边与路由设计

- 显式路由映射：条件边必须列出所有可能的目标节点
- 兜底路由：始终包含 `fallback` 或 `END` 路径，防止路由函数返回未映射值
- 迭代守卫：循环图必须有 `max_iterations` 限制 + `fingerprint` 重复检测
- 路由函数保持简单：只做状态判断，不做业务逻辑
  ```python
  # 推荐：路由函数只读 state，不修改
  def route(state: dict) -> str:
      if state.get("iteration", 0) >= state.get("max_iterations", 5):
          return "fallback"
      return state.get("next_action", "fallback")

  builder.add_conditional_edges("gate", route, {
      "schedule": "scheduler",
      "replan": "replan",
      "finalize": "finalize",
      "fallback": "error_handler",  # 兜底必须有
  })
  ```

## 4. 工具调用

- 使用 `@tool` 装饰器定义工具，自动生成 JSON schema
- ToolNode 开启 `handle_tool_errors=True`，工具异常不会崩溃整个图
- 工具函数保持幂等，同一参数多次调用结果一致
- 工具返回结构化数据（dict/list），不返回大段原始文本
- 多工具场景用 `bind_tools([tool1, tool2])` 一次绑定
  ```python
  tool_node = ToolNode(tools, handle_tool_errors=True)
  llm_with_tools = llm.bind_tools(tools)
  ```

## 5. Checkpoint 管理

- 开发/测试用 `MemorySaver`，生产用 Redis 或 Postgres
- thread_id 命名约定：`tenant:{id}:task:{id}`，带业务语义
- ResilientCheckpointer 包装：写入失败降级为日志，不阻塞主流程
- 定期清理历史 checkpoint，防止存储膨胀
- 设置 checkpoint TTL（Redis 的 `EXPIRE`），推荐 24-72 小时
  ```python
  # 生产环境：Redis + ResilientCheckpointer
  checkpointer = CheckpointManager(redis_url="redis://:123456@localhost:6379/0")

  # 开发环境：内存
  checkpointer = MemorySaver()
  ```

## 6. 流式输出

- 面向用户的聊天界面用 `messages` 模式（token 级流式）
- 前端状态同步用 `updates` 模式（只传增量）
- 调试和日志用 `values` 模式（完整状态快照）
- 自定义进度通知用 `custom` 模式
- SSE 端点设置心跳间隔（15-30s），防止代理/负载均衡器超时断开
  ```python
  # 聊天界面
  async for event in graph.astream_events(input, version="v2"):
      if event["event"] == "on_chat_model_stream":
          yield f"data: {event['data']['chunk'].content}\n\n"
  ```

## 7. 子图设计

- 子图独立编译，拥有独立状态空间
- 父子图通过重叠 key 自动共享数据，非重叠 key 为子图私有
- 避免子图状态泄漏到父图：子图内部字段不要出现在父图 schema 中
- 复杂系统用双图架构：GlobalGraph 做控制平面，SubtaskGraph 做数据平面
  ```python
  # 子图独立编译
  sub_graph = sub_builder.compile()
  # 作为父图节点嵌入
  parent_builder.add_node("sub", sub_graph)
  ```

## 8. 人机协作

- `interrupt_before` 用于危险操作前确认（删除、支付、发布）
- `interrupt_after` 用于结果审核（LLM 生成内容审核）
- 动态中断 `interrupt()` 用于条件性暂停（只在高风险时中断）
- 恢复时必须传相同的 `thread_id`，确保从正确的 checkpoint 继续
- 审批流设计：interrupt → 用户输入 → `Command(resume=value)` → 继续执行
  ```python
  # 恢复执行
  graph.invoke(Command(resume=user_input), config={"configurable": {"thread_id": thread_id}})
  ```

## 9. 错误处理

- 分级处理：区分 TRANSIENT（可重试）/ PERMANENT（不可重试）/ DEGRADABLE（可降级）
- 降级策略：非关键路径失败时返回默认值继续，不阻塞主流程
- 升级机制：连续失败超过阈值时中断并通知上层（EscalationReport）
- 结构化错误：错误信息写入 `state["error"]`，路由函数据此决定下一步
- 重试用指数退避：`countdown = base * (2 ** retry_count)`，设置 max_retries
  ```python
  # 错误分级处理
  if error_type == "TRANSIENT" and retry_count < max_retries:
      return {"next_action": "retry", "retry_count": retry_count + 1}
  elif error_type == "DEGRADABLE":
      return {"next_action": "continue", "result": default_value}
  else:
      return {"next_action": "fallback", "error": str(e)}
  ```

## 10. 多 Agent 编排

- 单控制平面原则：一个 Supervisor 管理所有 Worker，避免多头指挥
- Worker 之间不直接通信（除非 Swarm 模式），通过共享状态协调
- Plan-Execute-Replan 循环设置 `max_replan_count`（推荐 ≤ 3）
- 双图架构：GlobalGraph 做控制（plan/schedule/evaluate），SubtaskGraph 做执行（retrieve/generate）
- 黑板模式：共享状态 + 角色权限矩阵，每个 Agent 只能写自己负责的字段

## 11. Celery 集成

- 图节点内只分发任务（`send_task`），绝不 `.get()` 等待结果
- 用 `resume_orchestrator` 模式恢复图执行：Celery 回调触发 `graph.ainvoke(None, thread_id)`
- Celery task 是 async-first 逻辑的薄同步包装：`asyncio.run(async_fn())`
- 不同类型任务分队列部署：`orchestrate_jobs`、`retrieval_jobs`、`generation_jobs`
  ```python
  # 图节点内：只分发，不等待
  async def dispatch_node(state: dict) -> dict:
      task_id = celery_app.send_task("heavy_task", kwargs={...}, queue="retrieval_jobs").id
      return {"pending_task_id": task_id}

  # Celery 回调：恢复图执行
  @celery_app.task(queue="orchestrate_jobs")
  def resume_orchestrator(result: dict):
      asyncio.run(graph.ainvoke(None, config={"configurable": {"thread_id": result["thread_id"]}}))
  ```

## 12. 性能优化

- 并行节点：无依赖的节点用 `Send()` 并行执行，减少总延迟
- 缓存：重复查询结果缓存到 Store，避免重复 LLM 调用
- 流式输出：面向用户的场景用 `stream_mode="messages"`，减少首字延迟
- Checkpoint 精简：状态只存引用，减少每步序列化数据量
- 批量处理：多个子任务用 `Send` fan-out 并行，reducer 自动聚合结果

## 13. 测试策略

- 单元测试：直接调用节点函数，构造输入 state → 调用 → 断言输出
- 集成测试：用 `MemorySaver` 运行完整图，断言最终状态
- Mock LLM：用 `FakeListChatModel` 做确定性测试，无需 API key
- 端到端测试：用真实 LLM 运行关键路径，验证 prompt 效果
- 回归测试：固定输入/输出快照，防止重构引入 bug
  ```python
  # 单元测试：节点是纯函数
  async def test_retrieve_node():
      state = {"query": "test", "document_ids": []}
      result = await retrieve(state)
      assert "document_ids" in result
      assert len(result["document_ids"]) > 0

  # 集成测试：完整图
  def test_full_graph():
      result = graph.invoke({"messages": [("human", "hello")]})
      assert result["messages"][-1].content != ""
  ```
