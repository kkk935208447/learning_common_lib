# LangGraph 常见陷阱

## 1. 状态突变（直接修改 state）

### 直接 append / 赋值

```python
# ❌ 错误：直接修改 state 中的 list
async def bad_node(state: dict) -> dict:
    state["messages"].append(new_msg)  # 直接修改！
    return state

# ✅ 正确：返回新的更新，让 reducer 合并
async def good_node(state: dict) -> dict:
    return {"messages": [new_msg]}  # reducer 自动合并
```

**问题分析**：LangGraph 依赖 reducer 合并状态更新。直接修改会绕过 reducer，导致 checkpoint 记录的是突变前的快照，恢复时丢失数据。

### 嵌套对象修改

```python
# ❌ 错误：修改嵌套 dict
async def bad_node(state: dict) -> dict:
    state["config"]["temperature"] = 0.5  # 嵌套修改同样危险
    return state

# ✅ 正确：返回完整的新 config
async def good_node(state: dict) -> dict:
    new_config = {**state["config"], "temperature": 0.5}
    return {"config": new_config}
```

### dict 直接赋值覆盖

```python
# ❌ 错误：直接往 state dict 里塞新 key
async def bad_node(state: dict) -> dict:
    state["new_field"] = "value"  # 绕过 reducer
    return state

# ✅ 正确：只返回需要更新的字段
async def good_node(state: dict) -> dict:
    return {"new_field": "value"}
```

**问题分析**：所有对 state 的修改都必须通过返回值传递给 reducer。直接赋值、append、嵌套修改都会导致 checkpoint 不一致，在 interrupt 恢复后出现"状态丢失"的诡异 bug。

## 2. 无限循环（缺少迭代守卫）

### 基本迭代守卫

```python
# ❌ 错误：没有退出条件
def route(state: dict) -> str:
    if state.get("need_more"):
        return "agent"  # 可能永远循环
    return END

# ✅ 正确：加迭代守卫
def route(state: dict) -> str:
    if state.get("iteration", 0) >= state.get("max_iterations", 5):
        return END  # 强制退出
    if state.get("need_more"):
        return "agent"
    return END
```

### fingerprint 检测死循环

```python
# ❌ 错误：状态没有实质变化但一直循环
async def agent_node(state: dict) -> dict:
    # LLM 每次返回相同的 tool_call，状态不变，无限循环
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}

# ✅ 正确：用 fingerprint 检测状态是否真正变化
async def agent_node(state: dict) -> dict:
    response = await llm.ainvoke(state["messages"])
    current_fp = hashlib.md5(str(response.content).encode()).hexdigest()
    if current_fp == state.get("last_fingerprint"):
        return {"messages": [AIMessage(content="检测到重复，终止循环")], "need_more": False}
    return {"messages": [response], "last_fingerprint": current_fp}
```

### 递归深度限制

```python
# ✅ 在图编译时设置全局递归限制
graph = builder.compile(checkpointer=checkpointer)
result = graph.invoke(
    inputs,
    config={"recursion_limit": 25}  # 默认 25，生产环境建议 ≤ 50
)
```

**问题分析**：LangGraph 默认 `recursion_limit=25`，超过后抛出 `GraphRecursionError`。但依赖默认值不够安全——应在路由函数中主动检测迭代次数和状态变化，避免浪费 token。

## 3. Checkpoint 膨胀

```python
# ❌ 错误：大对象存入状态
class BadState(TypedDict):
    full_documents: list[dict]  # 每个文档 5KB，10 轮迭代 = 50KB/checkpoint

# ✅ 正确：只存引用
class GoodState(TypedDict):
    document_ids: list[str]  # 几十字节
```

**问题分析**：每个 superstep 都会保存完整 state 快照。假设 state 含 10 个文档（每个 5KB），经过 20 轮迭代，checkpoint 存储量 = 50KB × 20 = 1MB/会话。1000 个并发会话 = 1GB。

### 清理策略

```python
# ✅ 定期清理旧 checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

# 方案 1：只保留最近 N 个 checkpoint
checkpointer = SqliteSaver.from_conn_string(":memory:")

# 方案 2：对话结束后主动清理
async def cleanup_thread(thread_id: str):
    """保留最新 checkpoint，删除历史"""
    # 根据你的存储后端实现清理逻辑
    pass

# 方案 3：state 中只存摘要，不存原始数据
class CompactState(TypedDict):
    summary: str           # 对话摘要，几百字节
    document_ids: list[str]  # 引用 ID
    # 原始文档存在外部存储（S3/数据库）
```

## 4. 阻塞事件循环

### requests 同步调用

```python
# ❌ 错误：在 async 节点中调用同步 IO
async def bad_node(state: dict) -> dict:
    result = requests.get("https://api.example.com")  # 阻塞！
    return {"data": result.json()}

# ✅ 正确：使用 async HTTP 库
async def good_node(state: dict) -> dict:
    async with httpx.AsyncClient() as client:
        result = await client.get("https://api.example.com")
    return {"data": result.json()}
```

### time.sleep 阻塞

```python
# ❌ 错误：同步 sleep 阻塞整个事件循环
async def bad_node(state: dict) -> dict:
    time.sleep(5)  # 所有协程都被卡住
    return {"status": "done"}

# ✅ 正确：使用 asyncio.sleep
async def good_node(state: dict) -> dict:
    await asyncio.sleep(5)  # 不阻塞其他协程
    return {"status": "done"}
```

### 同步数据库调用

```python
# ❌ 错误：在 async 节点中用同步 ORM
async def bad_node(state: dict) -> dict:
    user = db.session.query(User).get(state["user_id"])  # 阻塞！
    return {"user_name": user.name}

# ✅ 正确：使用 async ORM 或 run_in_executor
async def good_node(state: dict) -> dict:
    # 方案 1：async ORM（推荐）
    async with async_session() as session:
        user = await session.get(User, state["user_id"])
    return {"user_name": user.name}

    # 方案 2：run_in_executor 包装同步调用
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(None, sync_get_user, state["user_id"])
    return {"user_name": user.name}
```

**问题分析**：async 节点运行在事件循环中，任何同步阻塞调用（requests、time.sleep、同步 DB）都会冻结整个循环，导致其他节点、流式输出、心跳检测全部停滞。

## 5. Celery .get() 死锁

```python
# ❌ 错误：在 async 节点中同步等待 Celery 结果
async def bad_node(state: dict) -> dict:
    task = celery_app.send_task("heavy_task", kwargs={...})
    result = task.get(timeout=30)  # 阻塞事件循环！
    return {"result": result}

# ✅ 正确方案 1：用 asyncio.to_thread 包装
async def good_node_v1(state: dict) -> dict:
    task = celery_app.send_task("heavy_task", kwargs={...})
    result = await asyncio.to_thread(task.get, timeout=30)  # 在线程池中等待
    return {"result": result}

# ✅ 正确方案 2：只分发，用 interrupt 等回调恢复
async def good_node_v2(state: dict) -> dict:
    task_id = celery_app.send_task("heavy_task", kwargs={...}).id
    return {"pending_task_id": task_id, "next_action": "__interrupt__"}
```

**问题分析**：Celery 的 `.get()` 是同步阻塞调用。在 async 上下文中直接调用会死锁事件循环。`asyncio.to_thread` 将阻塞调用移到线程池，是最简单的修复方式；interrupt 模式适合长时间任务。

## 6. 流式模式选错

| 场景 | 推荐模式 | 常见错误 |
|------|----------|----------|
| 聊天界面逐字输出 | `messages` | 用了 `values`（每步输出完整 state） |
| 前端状态同步 | `updates` | 用了 `values`（数据量大） |
| 调试 | `values` | 用了 `messages`（看不到完整状态） |
| 进度通知 | `custom` | 用了 `updates`（无法自定义事件） |
| 子图内部事件 | `events` | 用了 `updates`（看不到子图内部） |

### 流式模式混用

```python
# ❌ 错误：前端需要逐字输出，但用了 values 模式
async for chunk in graph.astream(inputs, stream_mode="values"):
    # 每个 chunk 是完整 state，前端无法做逐字渲染
    send_to_frontend(chunk)

# ✅ 正确：聊天场景用 messages 模式
async for event in graph.astream(inputs, stream_mode="messages"):
    # event 是 (AIMessageChunk, metadata) 元组，适合逐字推送
    chunk, metadata = event
    send_to_frontend(chunk.content)
```

### 多模式组合

```python
# ✅ 需要同时拿到状态更新和自定义事件时，可以组合
async for event in graph.astream(inputs, stream_mode=["updates", "custom"]):
    mode, data = event
    if mode == "custom":
        handle_progress(data)
    elif mode == "updates":
        handle_state_update(data)
```

**问题分析**：选错流式模式不会报错，但前端拿到的数据格式完全不同。`values` 每步返回完整 state（适合调试），`updates` 返回增量更新，`messages` 返回 LLM token 流。上线前务必确认前端期望的格式。

## 7. 条件边遗漏路径

```python
# ❌ 错误：遗漏了可能的返回值
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
})
# 如果 route_fn 返回 "fallback"，运行时报错：
# ValueError: Expected one of ['tool', 'end'], got 'fallback'

# ✅ 正确：覆盖所有可能路径
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
    "fallback": "error_handler",
})
```

### 路由函数返回值不稳定

```python
# ❌ 错误：LLM 返回的 tool_call 名称可能不在映射中
def route_fn(state: dict) -> str:
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        return last_msg.tool_calls[0]["name"]  # LLM 可能返回任意工具名
    return "end"

# ✅ 正确：做白名单校验
VALID_ROUTES = {"search_tool", "calc_tool", "end"}

def route_fn(state: dict) -> str:
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:
        tool_name = last_msg.tool_calls[0]["name"]
        if tool_name in VALID_ROUTES:
            return tool_name
        return "fallback"  # 未知工具走兜底
    return "end"
```

**问题分析**：条件边的映射 dict 是白名单。路由函数返回任何不在映射中的值都会抛 `ValueError`，导致整个图崩溃。特别是当路由依赖 LLM 输出时，必须做防御性校验。

## 8. 忘记设置入口节点

```python
# ❌ 错误：忘记 set_entry_point 或 add_edge(START, ...)
builder = StateGraph(MyState)
builder.add_node("a", node_a)
builder.add_node("b", node_b)
builder.add_edge("a", "b")
graph = builder.compile()  # 报错：没有入口点

# ✅ 正确方案 1：set_entry_point
builder.set_entry_point("a")
graph = builder.compile()

# ✅ 正确方案 2：从 START 显式连边（推荐，更清晰）
from langgraph.graph import START
builder.add_edge(START, "a")
graph = builder.compile()
```

**问题分析**：`compile()` 会校验图的连通性。没有从 `START` 到任何节点的边，图无法确定从哪里开始执行。推荐用 `add_edge(START, "a")` 而非 `set_entry_point`，因为前者与 `add_edge` 风格一致。

## 9. Reducer 误用

### 忘记加 reducer 导致列表被覆盖

```python
# ❌ 错误：list 字段没有 reducer，后写覆盖前写
class BadState(TypedDict):
    items: list[str]  # 默认 LastValue，后写覆盖

async def node_a(state: dict) -> dict:
    return {"items": ["a1", "a2"]}

async def node_b(state: dict) -> dict:
    return {"items": ["b1"]}
# 最终 items = ["b1"]，node_a 的结果丢失！

# ✅ 正确：用 Annotated 声明追加语义
class GoodState(TypedDict):
    items: Annotated[list[str], operator.add]
# 最终 items = ["a1", "a2", "b1"]
```

### add_messages 与普通 list reducer 混淆

```python
# ❌ 错误：消息列表用 operator.add，导致重复消息
class BadState(TypedDict):
    messages: Annotated[list, operator.add]
# 如果节点返回已存在的消息，会产生重复

# ✅ 正确：消息列表用 add_messages（按 ID 去重/更新）
class GoodState(TypedDict):
    messages: Annotated[list, add_messages]
```

**问题分析**：`add_messages` 会根据消息 ID 去重和更新，而 `operator.add` 只做简单拼接。对话场景必须用 `add_messages`，否则 interrupt 恢复后消息会重复。

## 10. 子图状态泄漏

```python
# ❌ 错误：子图和父图用完全相同的 State，内部字段暴露给父图
class SharedState(TypedDict):
    query: str
    internal_score: float  # 子图内部字段，不应暴露

parent_builder.add_node("sub", sub_graph)  # 子图的 internal_score 泄漏到父图

# ✅ 正确：子图用独立 State，只通过重叠 key 共享数据
class ParentState(TypedDict):
    query: str
    result: str

class SubState(TypedDict):
    query: str           # 重叠 key，自动共享
    result: str          # 重叠 key，自动共享
    internal_score: float  # 非重叠 key，子图私有
```

**问题分析**：父子图通过 key 名称重叠自动共享数据。如果子图的内部字段出现在父图 schema 中，会导致状态污染。设计原则：子图内部字段绝不出现在父图 schema 中。

## 11. Command 与 Send 混淆

```python
# ❌ 错误：想并行分发多个子任务，但用了 Command（只能单路由）
def route(state: dict) -> Command:
    for task in state["tasks"]:
        return Command(goto="worker", update={"current_task": task})
    # 只会执行第一个 task！

# ✅ 正确：并行分发用 Send
def route(state: dict) -> list[Send]:
    return [Send("worker", {"task": task}) for task in state["tasks"]]
```

```python
# ❌ 错误：想做 Agent 间 handoff，但用了 Send（会创建并行副本）
def route(state: dict) -> list[Send]:
    return [Send("agent_b", state)]  # 创建了 agent_b 的并行实例

# ✅ 正确：单路由 handoff 用 Command
def route(state: dict) -> Command:
    return Command(goto="agent_b", update={"handoff_from": "agent_a"})
```

**问题分析**：`Send` = 并行 fan-out（创建多个节点实例），`Command` = 单路由 handoff（控制权转移）。混用会导致意外的并行执行或丢失并行能力。

## 12. interrupt 恢复不一致

```python
# ❌ 错误：恢复时用了不同的 thread_id
graph.invoke(input, config={"configurable": {"thread_id": "t1"}})
# ... interrupt 暂停 ...
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": "t2"}})
# t2 没有 t1 的 checkpoint，从头开始执行！

# ✅ 正确：恢复时必须用相同的 thread_id
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": "t1"}})
```

```python
# ❌ 错误：interrupt 后修改了图的结构再恢复
graph_v1 = builder_v1.compile(checkpointer=saver)
graph_v1.invoke(input, config)  # interrupt 暂停
# ... 修改了图结构 ...
graph_v2 = builder_v2.compile(checkpointer=saver)
graph_v2.invoke(Command(resume="yes"), config)  # 节点名变了，恢复失败！

# ✅ 正确：图结构变更后，旧 checkpoint 不可恢复，需要重新执行
```

**问题分析**：Checkpoint 绑定 thread_id 和图结构。恢复时 thread_id 不匹配会找不到 checkpoint；图结构变更后旧 checkpoint 的节点引用可能失效。

## 13. Store namespace 冲突

```python
# ❌ 错误：不同用户共用同一 namespace
store.put(("memory",), "preferences", {"theme": "dark"})
# 所有用户共享同一个 preferences，互相覆盖！

# ✅ 正确：用 user_id 隔离 namespace
store.put(("memory", user_id), "preferences", {"theme": "dark"})
# 每个用户独立的 namespace
```

**问题分析**：Store 的 namespace 是 tuple 类型，用于隔离不同租户/用户的数据。忘记加用户维度会导致数据互相覆盖。命名约定：`("memory", tenant_id, user_id)`。

## 14. ToolNode 错误处理缺失

```python
# ❌ 错误：ToolNode 默认不处理工具异常，异常会崩溃整个图
tool_node = ToolNode(tools)
# 工具函数抛异常 → 图直接崩溃

# ✅ 正确：开启错误处理
tool_node = ToolNode(tools, handle_tool_errors=True)
# 工具异常 → 转为 ToolMessage(content="Error: ...") → LLM 可自我纠正
```

```python
# ❌ 错误：工具返回超大文本，LLM 上下文溢出
@tool
def search(query: str) -> str:
    results = fetch_all_results(query)
    return str(results)  # 可能返回几十 KB

# ✅ 正确：工具返回结构化摘要
@tool
def search(query: str) -> dict:
    results = fetch_all_results(query)
    return {
        "count": len(results),
        "top_3": [{"title": r.title, "snippet": r.snippet[:200]} for r in results[:3]],
    }
```

**问题分析**：`handle_tool_errors=True` 是生产必备配置。没有它，任何工具异常都会导致整个图崩溃。开启后，异常被转为错误消息返回给 LLM，LLM 可以选择重试或换一种方式调用。

## 排查清单

遇到问题时按此顺序排查：

1. **状态是否正确更新？** — 在节点前后打印 state，确认 reducer 是否生效
2. **路由函数返回值是否在映射中？** — 打印路由函数返回值，对照 `add_conditional_edges` 的映射 dict
3. **是否有无限循环？** — 检查 `iteration` 计数器和 `fingerprint` 变化
4. **Checkpoint 是否正常保存？** — 检查存储后端连接，用 `get_state()` 验证
5. **异步节点是否有同步阻塞调用？** — 搜索 `requests.`、`time.sleep`、`.get(timeout`
6. **错误是否被 safe_node 正确捕获？** — 检查 safe_node 装饰器是否包装了所有节点
7. **子图状态是否泄漏？** — 对比父子图 State schema，确认无意外重叠 key
8. **Send 和 Command 是否用对？** — 并行用 Send，单路由用 Command
9. **interrupt 恢复的 thread_id 是否一致？** — 打印恢复时的 config
10. **工具返回值是否过大？** — 检查 ToolMessage 内容长度

### 快速调试命令

```python
# 打印图拓扑
print(graph.get_graph().draw_mermaid())

# 打印当前状态
state = graph.get_state(config)
print(f"当前节点: {state.next}")
print(f"状态值: {state.values}")

# 打印状态历史
for s in graph.get_state_history(config):
    print(f"step={s.metadata.get('step')}, next={s.next}, ts={s.created_at}")

# 检查 checkpoint 存储
from langgraph.checkpoint.memory import MemorySaver
saver = MemorySaver()
print(list(saver.list(config)))
```
