from __future__ import annotations

"""
目标：演示 Store 数据的生命周期管理，而不只是 put/get/search。
关键 API：put/get/search/delete
运行命令：python 07_store_lifecycle_management.py
预期现象：
  1. 初次写入用户偏好
  2. 覆盖更新版本号
  3. 删除过时记录
  4. 打印每一步前后的 namespace 内容

生产提醒：
  - Store 不只是“能存下来”，还要考虑覆盖策略、删除策略和冷数据清理
  - 生命周期管理越明确，越不容易把 Store 变成无限增长的垃圾堆
"""

from langgraph.store.memory import InMemoryStore


def print_namespace(store: InMemoryStore, namespace: tuple[str, ...], title: str) -> None:
    print(title)
    items = store.search(namespace, limit=20)
    if not items:
        print("  (empty)")
        return
    for item in items:
        print(f"  key={item.key} value={item.value}")


def main() -> None:
    store = InMemoryStore()
    namespace = ("tenant", "acme", "users", "u1", "prefs")

    print("=== 1. 初次写入 ===")
    store.put(namespace, "favorite_topic", {"value": "差旅制度", "version": 1})
    store.put(namespace, "report_style", {"value": "bullet", "version": 1})
    print_namespace(store, namespace, "当前 namespace 内容:")

    print("\n=== 2. 覆盖更新 ===")
    store.put(namespace, "favorite_topic", {"value": "差旅规则变化", "version": 2})
    print_namespace(store, namespace, "覆盖后 namespace 内容:")

    print("\n=== 3. 删除过时记录 ===")
    store.delete(namespace, "report_style")
    print_namespace(store, namespace, "删除后 namespace 内容:")

    print("\n=== 4. 冷数据清理提示 ===")
    print("  生产环境应进一步补 TTL / 批量清理 / 版本迁移策略")


if __name__ == "__main__":
    main()
