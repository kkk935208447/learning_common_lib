# LangGraph 常见陷阱

## 1. 状态突变（直接修改 state）

```python
# 错误：直接修改 state
async def bad_node(state: dict) -> dict:
    state["messages"].append(new_msg)  # 直接修改！
    return state

# 正确：返回新的更新
async def good_node(state: dict) -> dict:
    return {"messages": [new_msg]}  # reducer 自动合并
```

原因：LangGraph 依赖 reducer 合并状态更新。直接修改会绕过 reducer，导致 checkpoint 不一致。

## 2. 无限循环（缺少迭代守卫）

```python
# 错误：没有退出条件
def route(state: dict) -> str:
    if state.get("need_more"):
        return "agent"  # 可能永远循环
    return END

# 正确：加迭代守卫
def route(state: dict) -> str:
    if state.get("iteration", 0) >= state.get("max_iterations", 5):
        return END  # 强制退出
    if state.get("need_more"):
        return "agent"
    return END
```

建议：所有循环图都设置 `max_iterations`，生产环境建议 ≤ 10。

## 3. Checkpoint 膨胀

```python
# 错误：大对象存入状态
class BadState(TypedDict):
    full_documents: list[dict]  # 每个文档几 KB，10 轮迭代 = 几十 MB

# 正确：只存引用
class GoodState(TypedDict):
    document_ids: list[str]  # 几十字节
```

每个 superstep 都会保存完整 state 快照。大对象会导致 checkpoint 存储爆炸。

## 4. 阻塞事件循环

```python
# 错误：在 async 节点中调用同步 IO
async def bad_node(state: dict) -> dict:
    result = requests.get("https://api.example.com")  # 阻塞！
    return {"data": result.json()}

# 正确：使用 async 库或 run_in_executor
async def good_node(state: dict) -> dict:
    async with httpx.AsyncClient() as client:
        result = await client.get("https://api.example.com")
    return {"data": result.json()}
```

## 5. Celery .get() 死锁

```python
# 错误：在 async 节点中同步等待 Celery 结果
async def bad_node(state: dict) -> dict:
    task = celery_app.send_task("heavy_task", kwargs={...})
    result = task.get(timeout=30)  # 阻塞事件循环！
    return {"result": result}

# 正确：只分发，不等待；用回调恢复
async def good_node(state: dict) -> dict:
    task_id = await dispatch_to_celery("heavy_task", {...})
    return {"pending_task_id": task_id, "next_action": "__interrupt__"}
```

Celery 的 `.get()` 是同步阻塞调用，在 async 上下文中会死锁整个事件循环。

## 6. 流式模式选错

| 场景 | 推荐模式 | 常见错误 |
|------|----------|----------|
| 聊天界面逐字输出 | `messages` | 用了 `values`（每步输出完整 state） |
| 前端状态同步 | `updates` | 用了 `values`（数据量大） |
| 调试 | `values` | 用了 `messages`（看不到完整状态） |
| 进度通知 | `custom` | 用了 `updates`（无法自定义事件） |

## 7. 条件边遗漏路径

```python
# 错误：遗漏了可能的返回值
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
})
# 如果 route_fn 返回 "fallback"，运行时报错！

# 正确：覆盖所有可能路径
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
    "fallback": "error_handler",
})
```

## 8. 忘记设置入口节点

```python
# 错误：忘记 set_entry_point
builder = StateGraph(MyState)
builder.add_node("a", node_a)
graph = builder.compile()  # 运行时报错

# 正确
builder.set_entry_point("a")
graph = builder.compile()
```

## 排查清单

遇到问题时按此顺序排查：

1. 状态是否正确更新？（打印每步 state）
2. 路由函数返回值是否在映射中？
3. 是否有无限循环？（检查迭代计数）
4. Checkpoint 是否正常保存？（检查存储后端连接）
5. 异步节点是否有同步阻塞调用？
6. 错误是否被 safe_node 正确捕获？
