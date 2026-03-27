from __future__ import annotations

"""
目标：演示 checkpoint schema 演进时，如何兼容旧状态。
关键 API：MemorySaver、同一个 thread_id、ainvoke(None, config)
运行命令：python 05_checkpoint_schema_evolution.py
预期现象：
  1. V1 图先写入旧 checkpoint
  2. V2 图用同一 checkpointer + 同一 thread_id 恢复旧状态
  3. V2 节点为缺失字段补默认值，而不是假设字段一定存在
生产提醒：
  - 新增 state 字段时，节点必须用 `state.get(...)` 提供默认值
  - checkpoint 是运行时恢复点，不是 schema 严格受控的业务真理源
  - 本例通过 `aget_state()` 读取旧 checkpoint 后再交给 V2 图，目的是显式展示“兼容旧 state 结构”的心智
"""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class V1State(TypedDict, total=False):
    request_id: str
    query: str
    status: str


class V2State(TypedDict, total=False):
    request_id: str
    query: str
    status: str
    schema_version: int
    priority: str
    migration_note: str


def v1_prepare(state: V1State) -> dict:
    print("[V1] 写入旧版 checkpoint")
    return {"status": "planned"}


def v2_migrate(state: V2State) -> dict:
    schema_version = state.get("schema_version", 2)
    priority = state.get("priority", "normal")
    note = (
        "旧 checkpoint 中没有 priority 字段，"
        "V2 节点必须显式补默认值"
        if "priority" not in state
        else "checkpoint 已包含 priority"
    )
    print("[V2] 从旧 checkpoint 恢复")
    print(f"  request_id={state.get('request_id')}")
    print(f"  status={state.get('status')}")
    print(f"  priority={priority}")
    return {
        "schema_version": schema_version,
        "priority": priority,
        "migration_note": note,
        "status": "migrated",
    }


async def main() -> None:
    checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": "schema-evolution-demo"}}

    v1 = StateGraph(V1State)
    v1.add_node("prepare", v1_prepare)
    v1.add_edge(START, "prepare")
    v1.add_edge("prepare", END)
    app_v1 = v1.compile(checkpointer=checkpointer)

    print("=== 第一步：旧版本图写入 checkpoint ===")
    await app_v1.ainvoke(
        {"request_id": "req-001", "query": "整理差旅规则变化"},
        config=config,
    )
    snapshot_v1 = await app_v1.aget_state(config)
    print(f"V1 state: {snapshot_v1.values}\n")

    v2 = StateGraph(V2State)
    v2.add_node("migrate", v2_migrate)
    v2.add_edge(START, "migrate")
    v2.add_edge("migrate", END)
    app_v2 = v2.compile(checkpointer=checkpointer)

    print("=== 第二步：新版本图恢复旧 checkpoint ===")
    restored = await app_v2.aget_state(config)
    print(f"恢复到的旧 state: {restored.values}")
    print("兼容 checklist: 新字段用 get() / 旧字段可缺省 / 不假设 checkpoint 一定是当前版本")
    result_v2 = await app_v2.ainvoke(restored.values, config=config)
    print(f"V2 state: {result_v2}")


if __name__ == "__main__":
    asyncio.run(main())
