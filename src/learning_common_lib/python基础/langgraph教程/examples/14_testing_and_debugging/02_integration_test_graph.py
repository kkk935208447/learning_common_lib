"""完整图集成测试

目标：
    演示如何对完整的 LangGraph 图进行端到端集成测试，
    使用 mock checkpointer 验证图的整体行为。

关键 API：
    - graph.invoke() —— 执行完整图
    - MemorySaver —— 测试用 checkpointer
    - graph.get_state() —— 检查中间状态

运行命令：
    python 02_integration_test_graph.py

预期现象：
    构建完整图并执行端到端测试，验证输入→输出的正确性。

生产提醒：
    - 集成测试应覆盖主要执行路径（happy path + edge cases）
    - 使用 FakeListChatModel 避免依赖外部 API
    - 测试 checkpointer 的状态恢复能力
"""
from __future__ import annotations

from typing import Literal, TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph


# ── 被测图定义 ──────────────────────────────────────────
class OrderState(TypedDict):
    order_id: str
    action: str
    status: str
    result: str


def parse_action(state: OrderState) -> dict:
    """解析用户意图"""
    action = state["action"].lower()
    if "查询" in action or "查看" in action:
        return {"status": "query"}
    elif "取消" in action:
        return {"status": "cancel"}
    else:
        return {"status": "unknown"}


def route_action(state: OrderState) -> Literal["handle_query", "handle_cancel", "handle_unknown"]:
    """路由到对应处理节点"""
    status_map = {
        "query": "handle_query",
        "cancel": "handle_cancel",
    }
    return status_map.get(state["status"], "handle_unknown")


def handle_query(state: OrderState) -> dict:
    llm = FakeListChatModel(responses=[f"订单 {state['order_id']} 状态: 已发货"])
    result = llm.invoke(f"查询订单 {state['order_id']}")
    return {"result": result.content}


def handle_cancel(state: OrderState) -> dict:
    llm = FakeListChatModel(responses=[f"订单 {state['order_id']} 已取消"])
    result = llm.invoke(f"取消订单 {state['order_id']}")
    return {"result": result.content}


def handle_unknown(state: OrderState) -> dict:
    return {"result": "无法识别的操作，请重试"}


def build_order_graph(checkpointer=None):
    graph = StateGraph(OrderState)
    graph.add_node("parse", parse_action)
    graph.add_node("handle_query", handle_query)
    graph.add_node("handle_cancel", handle_cancel)
    graph.add_node("handle_unknown", handle_unknown)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", route_action)
    graph.add_edge("handle_query", END)
    graph.add_edge("handle_cancel", END)
    graph.add_edge("handle_unknown", END)

    return graph.compile(checkpointer=checkpointer)


# ══════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════

def test_query_order_e2e() -> None:
    """端到端测试：查询订单"""
    app = build_order_graph()
    result = app.invoke({
        "order_id": "ORD-001",
        "action": "查询订单状态",
        "status": "",
        "result": "",
    })
    assert result["status"] == "query"
    assert "ORD-001" in result["result"]
    assert "已发货" in result["result"]
    print("  [PASS] test_query_order_e2e")


def test_cancel_order_e2e() -> None:
    """端到端测试：取消订单"""
    app = build_order_graph()
    result = app.invoke({
        "order_id": "ORD-002",
        "action": "我要取消这个订单",
        "status": "",
        "result": "",
    })
    assert result["status"] == "cancel"
    assert "已取消" in result["result"]
    print("  [PASS] test_cancel_order_e2e")


def test_unknown_action_e2e() -> None:
    """端到端测试：未知操作"""
    app = build_order_graph()
    result = app.invoke({
        "order_id": "ORD-003",
        "action": "随便说点什么",
        "status": "",
        "result": "",
    })
    assert result["status"] == "unknown"
    assert "无法识别" in result["result"]
    print("  [PASS] test_unknown_action_e2e")


def test_checkpoint_state_recovery() -> None:
    """测试 checkpoint 状态恢复"""
    checkpointer = MemorySaver()
    app = build_order_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "test-thread"}}

    # 执行一次
    result = app.invoke(
        {"order_id": "ORD-004", "action": "查询", "status": "", "result": ""},
        config=config,
    )

    # 从 checkpoint 恢复状态
    state = app.get_state(config)
    assert state.values["order_id"] == "ORD-004"
    assert state.values["status"] == "query"
    print("  [PASS] test_checkpoint_state_recovery")


def test_multiple_threads_isolation() -> None:
    """测试多线程状态隔离"""
    checkpointer = MemorySaver()
    app = build_order_graph(checkpointer=checkpointer)

    config_a = {"configurable": {"thread_id": "thread-A"}}
    config_b = {"configurable": {"thread_id": "thread-B"}}

    app.invoke(
        {"order_id": "ORD-A", "action": "查询", "status": "", "result": ""},
        config=config_a,
    )
    app.invoke(
        {"order_id": "ORD-B", "action": "取消", "status": "", "result": ""},
        config=config_b,
    )

    state_a = app.get_state(config_a)
    state_b = app.get_state(config_b)
    assert state_a.values["order_id"] == "ORD-A"
    assert state_b.values["order_id"] == "ORD-B"
    assert state_a.values["status"] != state_b.values["status"]
    print("  [PASS] test_multiple_threads_isolation")


if __name__ == "__main__":
    print("=== 图集成测试 ===\n")

    tests = [
        test_query_order_e2e,
        test_cancel_order_e2e,
        test_unknown_action_e2e,
        test_checkpoint_state_recovery,
        test_multiple_threads_isolation,
    ]

    passed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {test_fn.__name__}: {e}")

    print(f"\n结果: {passed}/{len(tests)} 通过")
