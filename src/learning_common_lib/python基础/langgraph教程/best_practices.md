# LangGraph 最佳实践

## 状态设计原则

1. 最小化状态：只存必要字段，大对象用引用（ID/URL）而非内联
2. 不可变更新：节点返回新 dict，不直接修改 state
3. 类型注解：使用 TypedDict 定义 schema，IDE 友好
4. Reducer 选择：消息列表用 `add_messages`，计数器用自定义 reducer

```python
# 好：引用而非内联
class GoodState(TypedDict):
    document_ids: list[str]  # 只存 ID

# 坏：大对象内联
class BadState(TypedDict):
    documents: list[dict]  # 完整文档存入状态，checkpoint 膨胀
```

## 节点设计原则

1. 纯函数：节点只依赖 state 输入，不依赖外部可变状态
2. safe_node 包装：生产环境必须包装，提供超时和异常兜底
3. 单一职责：一个节点做一件事
4. 幂等性：同样的输入产生同样的输出（便于重试）

```python
@safe_node(node_name="retriever", timeout_s=10)
async def retrieve(state: dict) -> dict:
    docs = await search(state["query"])
    return {"document_ids": [d.id for d in docs]}
```

## 边设计原则

1. 显式路由映射：条件边必须列出所有可能的目标
2. 兜底路由：始终包含 fallback/END 路径
3. 迭代守卫：循环图必须有 max_iterations 限制

```python
builder.add_conditional_edges("agent", route_fn, {
    "tool": "tool_node",
    "end": END,
    "fallback": "error_handler",  # 兜底
})
```

## 错误处理原则

1. 分级处理：区分 TRANSIENT / PERMANENT / DEGRADABLE
2. 降级策略：非关键路径失败时返回默认值继续
3. 升级机制：连续失败超过阈值时中断并通知
4. 结构化错误：错误信息写入 state["error"]，便于路由

## 性能优化

1. 并行节点：无依赖的节点用 `Send()` 并行执行
2. 缓存：重复查询结果缓存到 Store
3. 流式输出：面向用户的场景用 `stream_mode="messages"`
4. Checkpoint 精简：定期清理历史 checkpoint

## 测试策略

| 层级 | 方法 | 工具 |
|------|------|------|
| 单元测试 | 直接调用节点函数 | pytest |
| 集成测试 | 用 MemorySaver 运行完整图 | pytest + FakeListChatModel |
| 端到端测试 | 用真实 LLM 运行关键路径 | pytest + 真实 API |
| 回归测试 | 固定输入/输出快照 | pytest-snapshot |

```python
# 单元测试示例
async def test_retrieve_node():
    state = {"query": "test", "document_ids": []}
    result = await retrieve(state)
    assert "document_ids" in result
    assert len(result["document_ids"]) > 0
```
