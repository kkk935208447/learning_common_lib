# LangGraph 最佳实践 (Best Practices)

本文件恢复了原始教程里的分章节结构，同时统一校正为当前仓库和 async-first 教学口径。

## 1. 状态设计

- 最小化状态：只存必要字段，大对象用引用（ID/URL/外部工件 ref）而非内联
- 不可变更新：节点返回增量 `dict`，不要直接修改 state
- TypedDict 用 `total=False` 标记可选字段，避免初始化时缺字段报错
- Reducer 选择：
  - 消息列表用 `add_messages`
  - 普通聚合列表用 `operator.add`
  - 计数器用显式累加 reducer
- 状态字段命名约定：
  - `next_action` 驱动路由
  - `error` 记录异常
  - `iteration` / `max_iterations` 控制循环

```python
class GoodState(TypedDict, total=False):
    document_ids: list[str]
    messages: Annotated[list[AnyMessage], add_messages]
    iteration: int
    error: str | None
    next_action: str
```

避免：

```python
class BadState(TypedDict):
    full_documents: list[dict]
```

TypedDict vs Pydantic：

- 内部运行状态优先 TypedDict，轻量且更适合频繁合并
- 外部输入校验、复杂嵌套结构可以用 Pydantic

## 2. 节点设计

- 节点尽量保持纯函数：只依赖输入 state，不依赖隐式全局可变状态
- 一个节点做一件事：检索、评估、生成、汇总分开
- 生产环境建议统一包上 `safe_node`
- 节点应具备幂等性：checkpoint 恢复后重复执行不应带来灾难性副作用
- 节点超时按类型设置，例如：
  - intake = 5s
  - planner = 15s
  - retriever = 10s
  - evaluator = 10s
- 教程主线采用 async-first：

```python
@safe_node(node_name="retriever", timeout_s=10)
async def retrieve(state: dict) -> dict:
    docs = await search(state["query"])
    return {"document_ids": [d.id for d in docs]}
```

如果节点本身是同步逻辑，也建议在示例的主执行路径中继续使用 `ainvoke` / `astream`。

## 3. 边与路由设计

- 条件边必须显式列出所有可能目标
- 始终保留 `fallback` 或 `END` 路径
- 循环图至少有两层守卫：
  - `max_iterations`
  - fingerprint / 结果重复检测
- 路由函数只做判断，不做业务副作用

```python
def route(state: dict) -> str:
    if state.get("iteration", 0) >= state.get("max_iterations", 5):
        return "fallback"
    return state.get("next_action", "fallback")
```

## 4. 工具调用

- 使用 `@tool` 定义工具，自动生成 JSON schema
- `ToolNode` 优先作为图节点使用，而不是脱离运行时单独 `.invoke()`
- 多工具场景用 `ToolNode(tools, handle_tool_errors=True)`
- 工具函数保持幂等
- 工具返回尽量结构化，不返回无法消费的大段原始文本

```python
graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
graph.add_edge("tools", "llm")
```

## 5. Checkpoint 管理

- 开发 / 测试：`MemorySaver`
- 生产环境：Redis / Postgres 类后端
- `thread_id` 命名必须带业务语义
- Redis checkpoint 要明确环境前提：
  - 安装 `langgraph-checkpoint-redis`
  - Redis 具备 RediSearch / Redis Stack 能力
- 降级策略：
  - 初始化失败时回退到 `MemorySaver`
  - 不把存储层失败伪装成图编排错误

```python
checkpointer = await CheckpointManager(
    redis_url="redis://:123456@localhost:6379/0"
).get_checkpointer()
```

## 6. 流式输出

- 聊天逐 token 输出：`stream_mode="messages"`
- 前端状态同步：`stream_mode="updates"`
- 调试完整状态：`stream_mode="values"`
- 自定义进度：`stream_mode="custom"`
- 事件追踪：`astream_events(version="v2")`

```python
async for chunk, metadata in graph.astream(inputs, stream_mode="messages"):
    yield chunk.content
```

SSE 端点建议：

- 15-30s 心跳
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`
- 并发限制使用 `asyncio.Semaphore`

## 7. 子图设计

- 子图独立编译，拥有独立状态空间
- 父子图通过重叠 key 共享必要数据，非重叠 key 保持私有
- 父图与子图职责边界要清晰：
  - 父图负责控制面
  - 子图负责局部执行闭环
- 子图调用也建议 async-first：

```python
sub_result = await sub_graph.ainvoke(sub_input)
```

## 8. 人机协作

- 动态 `interrupt()` 是默认生产路径
- `interrupt_before` 用于固定危险操作前确认
- `interrupt_after` 用于固定结果审核点
- 恢复时必须带相同 `thread_id`
- 审批流设计：
  - `interrupt(payload)`
  - 用户输入
  - `Command(resume=value)`
  - 从 checkpoint 恢复继续执行

## 9. 错误处理

- 区分：
  - TRANSIENT：可重试
  - PERMANENT：不可重试
  - DEGRADABLE：可降级
- 错误统一写回 `state["error"]`
- 路由函数依据错误字段决定 retry / fallback / escalate
- 使用指数退避控制重试节奏

```python
if error_type == "TRANSIENT" and retry_count < max_retries:
    return {"next_action": "retry", "retry_count": retry_count + 1}
elif error_type == "DEGRADABLE":
    return {"next_action": "continue", "result": default_value}
return {"next_action": "fallback", "error": str(exc)}
```

## 10. 多 Agent 编排

- 单控制平面原则：一个 Supervisor / GlobalGraph 负责推进决策
- Worker 间默认不直接通信，通过共享状态或外部工件协调
- Plan-Execute-Replan 要设 `max_replan_count`
- 双图架构是复杂 AgenticRAG 的主力模式
- 黑板模式要约束“每个 Agent 只写自己的字段”

## 11. Celery 集成

- 图节点里只做 dispatch，不做同步等待
- 推荐控制流：
  1. dispatch Celery 任务
  2. 图进入等待态
  3. worker 外部回写结果
  4. 同 `thread_id` 恢复图执行
- `resume_orchestrator` 是“薄同步包装 + async 恢复逻辑”

```python
async def dispatch_node(state: dict) -> dict:
    task_id = celery_app.send_task("heavy_task", kwargs={...}, queue="retrieval_jobs").id
    return {"pending_task_id": task_id, "waiting_reason": "worker_result"}
```

## 12. 性能优化

- 无依赖节点用 `Send` 做 fan-out 并行
- 重复查询结果可缓存到 Store 或外部缓存
- 流式输出优先 `messages`，减少首字延迟
- checkpoint 精简：state 只存引用，不存大对象
- 大规模并行时控制 batch 大小，避免单轮 fan-out 爆内存

## 13. 测试策略

- 节点单元测试：直接调用节点函数
- 图集成测试：用 `MemorySaver` 跑完整图
- Mock LLM：用 `FakeListChatModel`
- 关键路径 smoke：跑示例和模板 demo
- 回归测试：固定输入和关键输出

```python
async def test_retrieve_node():
    state = {"query": "test", "document_ids": []}
    result = await retrieve(state)
    assert "document_ids" in result


def test_full_graph():
    result = graph.invoke({"messages": [("human", "hello")]})
    assert result["messages"][-1].content != ""
```

虽然测试文件本身可以同步或异步混用，但教程主线仍建议优先验证 async 执行路径。
