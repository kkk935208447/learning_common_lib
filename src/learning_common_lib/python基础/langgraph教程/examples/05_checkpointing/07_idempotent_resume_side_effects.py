"""
05_checkpointing / 07_idempotent_resume_side_effects

目标:
    演示恢复后副作用如何做到幂等。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    interrupt、同一 execution_id 的外部幂等保护

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/07_idempotent_resume_side_effects.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/05_checkpointing/07_idempotent_resume_side_effects.py

预期现象:
    1. 图先进入等待态
    2. 恢复后发送 webhook
    3. 模拟同一执行实例被重复回放时，不会重复发送 webhook

生产提醒:
    - checkpoint 恢复意味着“节点可能被再次执行”
    - 任何写 DB / 发消息 / 调外部 API 的副作用，都必须有 execution_id 幂等键
"""
from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


OUTBOX: dict[str, dict] = {}


class SideEffectState(TypedDict, total=False):
    execution_id: str
    request: str
    approval: str
    final_status: str


def prepare_request(state: SideEffectState) -> dict:
    """ 准备阶段：生成 execution_id"""
    execution_id = state.get("execution_id", "exec-side-effect-001")
    print(f"[prepare] execution_id={execution_id}")
    return {"execution_id": execution_id}


def wait_for_approval(state: SideEffectState) -> dict:
    """ 等待审批：中断等待审批者输入"""
    approval = interrupt(
        {
            "kind": "approval",
            "execution_id": state["execution_id"],
            "request": state.get("request", ""),
        }
    )
    return {"approval": str(approval)}


def emit_once(execution_id: str, payload: dict) -> str:
    """ 发送 webhook：幂等检查"""
    if execution_id in OUTBOX:
        print(f"[emit] 检测到重复回放，跳过 execution_id={execution_id}")
        return "duplicate_skipped"
    OUTBOX[execution_id] = payload
    print(f"[emit] 首次发送 webhook: execution_id={execution_id}")
    return "sent"


def send_webhook(state: SideEffectState) -> dict:
    """ 发送 webhook：幂等发送"""
    status = emit_once(
        state["execution_id"],
        {"request": state.get("request", ""), "approval": state.get("approval", "")},
    )
    return {"final_status": status}


async def main() -> None:
    saver = MemorySaver()
    graph = StateGraph(SideEffectState)
    graph.add_node("prepare", prepare_request)
    graph.add_node("wait", wait_for_approval)
    graph.add_node("send", send_webhook)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "wait")
    graph.add_edge("wait", "send")
    graph.add_edge("send", END)
    app = graph.compile(checkpointer=saver)
    get_langgraph_png(app, "07_idempotent_resume_side_effects.png")  # 导出图

    config = {"configurable": {"thread_id": "idempotent-side-effect"}}

    print("=== 第一次调用：进入等待态 ===")
    waiting = await app.ainvoke(
        {"request": "部署差旅规则知识库到生产"},
        config=config,
    )
    print(f"当前状态: {waiting}\n")

    print("=== 恢复执行：发送 webhook ===")
    completed = await app.ainvoke(Command(resume="approved"), config=config)
    print(f"最终状态: {completed}\n")

    print("=== 模拟重复回放同一 execution_id ===")
    replay_state = await app.aget_state(config)
    replay_result = send_webhook(replay_state.values)
    print(f"重复回放结果: {replay_result}")
    print(f"OUTBOX 条数: {len(OUTBOX)}")


def get_langgraph_png(app: StateGraph, file_name: str) -> None:
    from pathlib import Path
    PARENT_DIR = Path(__file__).resolve().parent   # 获得当前文件的父目录
    FILE_PATH = str(PARENT_DIR / file_name)
    # 画图 png
    app.get_graph().draw_mermaid_png(output_file_path=FILE_PATH)
    print(f"图已导出到 {FILE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
