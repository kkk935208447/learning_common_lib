# LangGraph 常见陷阱

本文件恢复了原始教程中更细的错误/正确对照，同时按当前版本口径修正了 streaming、Celery、Send、checkpoint 等描述。

## 1. 状态突变（直接修改 state）

### 直接 append / 赋值

```python
# ❌ 错误：直接修改 state 中的 list
async def bad_node(state: dict) -> dict:
    state["messages"].append(new_msg)
    return state

# ✅ 正确：返回新的更新，让 reducer 合并
async def good_node(state: dict) -> dict:
    return {"messages": [new_msg]}
```

问题分析：

- LangGraph 依赖 reducer 合并状态更新
- 直接修改会绕过 reducer
- checkpoint 恢复时容易出现“状态丢失”或“恢复后不一致”

### 嵌套对象修改

```python
# ❌ 错误：修改嵌套 dict
async def bad_node(state: dict) -> dict:
    state["config"]["temperature"] = 0.5
    return state

# ✅ 正确：返回完整的新 config
async def good_node(state: dict) -> dict:
    new_config = {**state["config"], "temperature": 0.5}
    return {"config": new_config}
```

### 整包返回整个 state

```python
# ❌ 错误：把整个 state 回填回去
async def bad_node(state: dict) -> dict:
    return {**state, "next_action": "continue"}

# ✅ 正确：只返回增量字段
async def good_node(state: dict) -> dict:
    return {"next_action": "continue"}
```

这类错误尤其容易污染 reducer 字段，例如重复追加 `messages`、`results`、`subtask_results`。

## 2. 无限循环（缺少迭代守卫）

### 基本迭代守卫

```python
# ❌ 错误：没有退出条件
def route(state: dict) -> str:
    if state.get("need_more"):
        return "agent"
    return END

# ✅ 正确：显式设置 guard
def route(state: dict) -> str:
    if state.get("iteration", 0) >= state.get("max_iterations", 5):
        return END
    if state.get("need_more"):
        return "agent"
    return END
```

### fingerprint 检测死循环

```python
async def agent_node(state: dict) -> dict:
    response = await llm.ainvoke(state["messages"])
    current_fp = hashlib.md5(str(response.content).encode()).hexdigest()
    if current_fp == state.get("last_fingerprint"):
        return {
            "messages": [AIMessage(content="检测到重复，终止循环")],
            "need_more": False,
        }
    return {"messages": [response], "last_fingerprint": current_fp}
```

### 递归深度限制

```python
result = await graph.ainvoke(
    inputs,
    config={"recursion_limit": 25},
)
```

`recursion_limit` 是最后兜底，不应代替显式迭代守卫。

## 3. Checkpoint 膨胀

```python
# ❌ 错误：大对象存入状态
class BadState(TypedDict):
    full_documents: list[dict]

# ✅ 正确：只存引用
class GoodState(TypedDict):
    document_ids: list[str]
```

问题分析：

- 每个 superstep 都可能保存完整 state 快照
- 大文档、多轮对话、检索结果全文都容易把 checkpoint 打爆

### 清理策略

- 只保留最近 N 个 checkpoint
- 会话结束后主动清理
- state 中只存摘要，不存原始数据

## 4. 阻塞事件循环

### requests 同步调用

```python
# ❌ 错误
async def bad_node(state: dict) -> dict:
    result = requests.get("https://api.example.com")
    return {"data": result.json()}

# ✅ 正确
async def good_node(state: dict) -> dict:
    async with httpx.AsyncClient() as client:
        result = await client.get("https://api.example.com")
    return {"data": result.json()}
```

### time.sleep 阻塞

```python
# ❌ 错误
async def bad_node(state: dict) -> dict:
    time.sleep(5)
    return {"status": "done"}

# ✅ 正确
async def good_node(state: dict) -> dict:
    await asyncio.sleep(5)
    return {"status": "done"}
```

### 同步数据库调用

```python
# ❌ 错误
async def bad_node(state: dict) -> dict:
    user = db.session.query(User).get(state["user_id"])
    return {"user_name": user.name}

# ✅ 正确
async def good_node(state: dict) -> dict:
    async with async_session() as session:
        user = await session.get(User, state["user_id"])
    return {"user_name": user.name}
```

问题分析：

- async 节点运行在事件循环中
- 同步阻塞会冻结其他协程、SSE、超时控制和心跳

## 5. Celery `.get()` 死锁 / 架构走偏

```python
# ❌ 错误：在 async 节点中同步等待 Celery 结果
async def bad_node(state: dict) -> dict:
    task = celery_app.send_task("heavy_task", kwargs={...})
    result = task.get(timeout=30)
    return {"result": result}
```

兼容性兜底：

```python
# 只作为兼容性兜底，不是推荐架构
result = await asyncio.to_thread(task.get, timeout=30)
```

推荐架构：

```python
async def good_node(state: dict) -> dict:
    task_id = celery_app.send_task("heavy_task", kwargs={...}).id
    return {"pending_task_id": task_id, "waiting_reason": "worker_result"}
```

然后通过：

1. worker 外部回写结果
2. 同 `thread_id` 恢复图执行

## 6. 流式模式选错

| 场景 | 推荐模式 | 常见错误 |
|------|----------|----------|
| 聊天界面逐字输出 | `messages` | 用 `values` 输出完整 state |
| 前端状态同步 | `updates` | 用 `values` 导致流量过大 |
| 调试完整状态 | `values` | 用 `messages` 看不到结构化状态 |
| 进度通知 | `custom` | 用 `updates` 无法表达业务事件 |
| trace / observability | `astream_events()` | 把它误当成默认聊天流 |

### 聊天流式

```python
# ✅ 推荐
async for chunk, metadata in graph.astream(inputs, stream_mode="messages"):
    send_to_frontend(chunk.content)
```

### 事件观测

```python
# ✅ 推荐
async for event in graph.astream_events(inputs, version="v2"):
    ...
```

当前版本里最容易混淆的一点就是把 `astream_events()` 误写成 `stream_mode="events"` 主流路径。

## 7. 条件边遗漏路径

```python
# ❌ 错误：遗漏 fallback
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
})
```

如果 `route_fn` 返回未映射值，会直接报错。

```python
# ✅ 正确：覆盖所有分支
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
    "fallback": "error_handler",
})
```

## 8. `Send` 用错位置

```python
# ❌ 错误：把 Send 当成节点返回值
def dispatch(state: State) -> list[Send]:
    return [Send("worker", {"task": task}) for task in state["tasks"]]
```

当前版本下这通常会触发：

- `InvalidUpdateError`
- `Expected dict, got [Send(...)]`

正确写法：

```python
def dispatch(state: State) -> dict:
    return {"queued_tasks": state["tasks"]}


def route_workers(state: State) -> list[Send]:
    return [Send("worker", {"task": task}) for task in state["queued_tasks"]]
```

## 9. ToolNode 直接调用

在当前版本里，`ToolNode` 的主路径是图节点，而不是“脱离运行时直接 `.invoke()` 的普通函数”。

推荐：

- 教学里手动执行 `tool.invoke(args)`，理解 ToolMessage 结构
- agent 流里把 `ToolNode` 接到图里

## 10. Thread / 恢复点用错

```python
# ❌ 错误：恢复时 thread_id 不一致
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": "t2"}})

# ✅ 正确：恢复必须使用同一个 thread_id
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": "t1"}})
```

对 checkpoint 恢复来说，`thread_id` 是执行线的身份标识，不是一个可随手替换的字符串。

## 11. 版本切换后误复用旧 checkpoint

如果你改了：

- 节点名
- state schema
- 路由 key
- 中断点结构

旧 checkpoint 可能已经不兼容。

建议：

- 版本升级后切换新的 `thread_id namespace`
- 或主动清理旧 checkpoint

## 12. 入口点 / 终点设置错误

```python
# ❌ 错误：忘记入口
builder = StateGraph(MyState)
builder.add_node("a", node_a)
builder.compile()
```

推荐：

```python
builder.add_edge(START, "a")
builder.add_edge("a", END)
```

当前教程仍会演示旧 API `set_entry_point` / `set_finish_point`，但生产主线推荐统一使用 `START` / `END`。

## 13. 控制面和执行面混在一起

在 multi-agent / AgenticRAG 系统里，最危险的不是模型效果差，而是职责乱：

- 调度器在决定下一步
- worker 也在决定下一步
- callback 也在决定下一步

推荐：

- `GlobalGraph` 统一负责推进决策
- `SubtaskGraph` 只负责局部闭环
- worker 通过结果回写和升级协议与控制面协作

## 14. 把 checkpoint 当成业务真理源

```python
# ❌ 错误：把业务状态只写到 checkpoint
return {"status": "COMPLETED", "final_answer": "..."}
```

问题：

- checkpoint 只保证“图能从这里恢复”
- 它不提供审计事件、查询能力、跨系统一致性

正确做法：

- 业务真理源写 MySQL / 事件表 / 任务表
- checkpoint 只保留最小运行态

## 15. 子 agent 只是函数，不是图

```python
# ❌ 错误：worker 只是一个裸函数
def researcher(state): ...
```

问题：

- 没有局部闭环
- 没有本地重试/校验/escalate
- 父图看不到结构化结果契约

更真实的教学路径：

- worker 至少应是 `prepare -> execute -> verify -> done/escalate` 子图

## 16. SSE 没有 heartbeat / Last-Event-ID

如果你只会：

- `yield token`

但没有：

- `heartbeat`
- `Last-Event-ID`
- replay 语义

前端一断线就会失去进度上下文。

## 17. resume_orchestrator 直接做调度

错误心智：

- worker 完成后，恢复器自己决定下一个 READY 子任务

正确心智：

- 恢复器只做 accepted/stale 判定
- 然后用同一个 `thread_id` 恢复图
- 真正的下一步仍由 `GlobalGraph` 决定
