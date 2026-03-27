"""
12_memory_and_store / 05_store_namespace_and_recall

目标:
    演示 store namespace 设计与召回。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    InMemoryStore.put/get/search

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/12_memory_and_store/05_store_namespace_and_recall.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/12_memory_and_store/05_store_namespace_and_recall.py

预期现象:
    1. 不同 tenant/user 的 namespace 相互隔离
    2. search 可以按 namespace 前缀召回

生产提醒:
    - namespace 设计是长期记忆隔离的第一道防线
    - 不要把所有用户偏好都塞进一个扁平 key 空间
"""
from __future__ import annotations

from langgraph.store.memory import InMemoryStore


def main() -> None:
    store = InMemoryStore()

    store.put(("tenant", "acme", "users", "u1"), "favorite_topic", {"value": "差旅制度"})
    store.put(("tenant", "acme", "users", "u2"), "favorite_topic", {"value": "报销规则"})
    store.put(("tenant", "beta", "users", "u1"), "favorite_topic", {"value": "采购流程"})

    print("=== 精确读取 ===")
    item = store.get(("tenant", "acme", "users", "u1"), "favorite_topic")
    print(f"acme/u1 -> {item.value if item else None}")

    print("\n=== 同租户搜索 ===")
    for item in store.search(("tenant", "acme")):
        print(f"  namespace={item.namespace} key={item.key} value={item.value}")

    print("\n=== 跨租户不会混淆 ===")
    for item in store.search(("tenant", "beta")):
        print(f"  namespace={item.namespace} key={item.key} value={item.value}")


if __name__ == "__main__":
    main()
