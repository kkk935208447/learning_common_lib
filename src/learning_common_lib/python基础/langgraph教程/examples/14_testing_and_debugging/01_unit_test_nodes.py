"""节点函数单元测试

目标：
    演示如何对 LangGraph 节点函数进行单元测试。
    节点本质是纯函数：构造输入状态 → 调用 → 断言输出。

关键 API：
    - 直接调用节点函数（无需构建图）
    - assert 断言验证输出

运行命令：
    python 01_unit_test_nodes.py

预期现象：
    所有 assert 通过，打印测试成功信息。

生产提醒：
    - 节点函数应设计为纯函数（相同输入 → 相同输出）
    - 副作用（API 调用、数据库写入）应通过依赖注入或 mock 隔离
    - 生产项目建议使用 pytest 框架，这里用 assert 简化演示
"""
from __future__ import annotations

from typing import TypedDict


# ══════════════════════════════════════════════════════════
# 被测节点函数
# ══════════════════════════════════════════════════════════

class State(TypedDict):
    query: str
    category: str
    confidence: float
    response: str


def classify_node(state: State) -> dict:
    """分类节点：根据 query 内容判断类别"""
    query = state["query"].lower()
    if "价格" in query or "费用" in query:
        return {"category": "pricing", "confidence": 0.95}
    elif "故障" in query or "报错" in query:
        return {"category": "support", "confidence": 0.90}
    else:
        return {"category": "general", "confidence": 0.70}


def respond_node(state: State) -> dict:
    """响应节点：根据分类生成回复"""
    templates = {
        "pricing": "关于价格问题，我们的方案从 99 元起。",
        "support": "收到您的技术问题，正在为您排查。",
        "general": "感谢咨询，请问有什么可以帮您？",
    }
    response = templates.get(state["category"], "未知分类")
    return {"response": response}


def validate_node(state: State) -> dict:
    """验证节点：检查置信度是否达标"""
    if state["confidence"] < 0.8:
        return {"response": f"置信度不足({state['confidence']})，转人工处理"}
    return {}


# ══════════════════════════════════════════════════════════
# 单元测试
# ══════════════════════════════════════════════════════════

def test_classify_pricing() -> None:
    """测试价格类查询的分类"""
    state: State = {"query": "这个产品价格多少？", "category": "", "confidence": 0.0, "response": ""}
    result = classify_node(state)
    assert result["category"] == "pricing", f"期望 pricing，实际 {result['category']}"
    assert result["confidence"] >= 0.9, f"置信度应 >= 0.9，实际 {result['confidence']}"
    print("  [PASS] test_classify_pricing")


def test_classify_support() -> None:
    """测试技术支持类查询的分类"""
    state: State = {"query": "系统报错了", "category": "", "confidence": 0.0, "response": ""}
    result = classify_node(state)
    assert result["category"] == "support"
    print("  [PASS] test_classify_support")


def test_classify_general() -> None:
    """测试通用查询的分类"""
    state: State = {"query": "你好", "category": "", "confidence": 0.0, "response": ""}
    result = classify_node(state)
    assert result["category"] == "general"
    assert result["confidence"] < 0.9  # 通用类别置信度较低
    print("  [PASS] test_classify_general")


def test_respond_pricing() -> None:
    """测试价格类回复"""
    state: State = {"query": "", "category": "pricing", "confidence": 0.95, "response": ""}
    result = respond_node(state)
    assert "99" in result["response"], "价格回复应包含价格信息"
    print("  [PASS] test_respond_pricing")


def test_respond_unknown_category() -> None:
    """测试未知分类的回复"""
    state: State = {"query": "", "category": "unknown", "confidence": 0.5, "response": ""}
    result = respond_node(state)
    assert result["response"] == "未知分类"
    print("  [PASS] test_respond_unknown_category")


def test_validate_low_confidence() -> None:
    """测试低置信度触发人工转接"""
    state: State = {"query": "", "category": "general", "confidence": 0.5, "response": ""}
    result = validate_node(state)
    assert "转人工" in result["response"]
    print("  [PASS] test_validate_low_confidence")


def test_validate_high_confidence() -> None:
    """测试高置信度正常通过"""
    state: State = {"query": "", "category": "pricing", "confidence": 0.95, "response": ""}
    result = validate_node(state)
    assert result == {}, "高置信度不应修改状态"
    print("  [PASS] test_validate_high_confidence")


if __name__ == "__main__":
    print("=== 节点函数单元测试 ===\n")

    tests = [
        test_classify_pricing,
        test_classify_support,
        test_classify_general,
        test_respond_pricing,
        test_respond_unknown_category,
        test_validate_low_confidence,
        test_validate_high_confidence,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 个测试")
