"""
05_checkpointing / 03_time_travel

目标:
    演示时间旅行——回溯到历史 checkpoint 并从任意历史点分叉执行

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    get_state_history, checkpoint_id, update_state

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/03_time_travel.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/05_checkpointing/03_time_travel.py

预期现象:
    1. 多轮对话后，列出所有历史 checkpoint
    2. 选择某个历史 checkpoint，查看当时的状态
    3. 从历史 checkpoint 分叉，注入新消息继续执行

生产提醒:
    - get_state_history 返回的是倒序列表（最新在前）
    - 从历史点恢复时，后续的 checkpoint 不会被删除（分叉而非覆盖）
    - 大量 checkpoint 会占用内存，生产环境需要 TTL 策略
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph


def chatbot(state: MessagesState) -> dict:
    """聊天节点：回复并标注轮次"""
    msg_count = len([m for m in state["messages"] if isinstance(m, HumanMessage)])
    return {
        "messages": [
            AIMessage(content=f"[轮次{msg_count}] 已收到，当前共 {len(state['messages'])} 条消息")
        ]
    }


def main() -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", chatbot)
    graph.set_entry_point("chatbot")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "time-travel-demo"}}

    # ── 1. 进行多轮对话，积累 checkpoint ────────────────────
    print("=== 多轮对话 ===")
    questions = ["第一个问题", "第二个问题", "第三个问题"]
    for q in questions:
        result = app.invoke({"messages": [HumanMessage(content=q)]}, config=config)
        print(f"  用户: {q}")
        print(f"  助手: {result['messages'][-1].content}")

    # ── 2. 列出所有历史 checkpoint ──────────────────────────
    print("\n=== 历史 Checkpoint 列表（最新在前）===")
    history = list(app.get_state_history(config))
    for i, state_snapshot in enumerate(history):
        cp_id = state_snapshot.config["configurable"].get("checkpoint_id", "N/A")
        msg_count = len(state_snapshot.values.get("messages", []))
        print(f"  [{i}] checkpoint_id={cp_id[:20]}... 消息数={msg_count}")

    # ── 3. 回溯到第一轮对话后的状态 ─────────────────────────
    # history 是倒序的，最后一个元素是最早的状态
    # 找到只有 2 条消息的 checkpoint（第一轮对话后：1条用户 + 1条助手）
    target_snapshot = None
    for snap in history:
        if len(snap.values.get("messages", [])) == 2:
            target_snapshot = snap
            break

    if target_snapshot:
        target_cp_id = target_snapshot.config["configurable"]["checkpoint_id"]
        print(f"\n=== 回溯到 checkpoint: {target_cp_id[:20]}... ===")
        print(f"  该时刻的消息:")
        for msg in target_snapshot.values["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            print(f"    [{role}] {msg.content}")

        # ── 4. 从历史点分叉执行 ─────────────────────────────
        print("\n=== 从历史点分叉 ===")
        fork_config = {
            "configurable": {
                "thread_id": "time-travel-demo",
                "checkpoint_id": target_cp_id,
            }
        }
        # 从第一轮后的状态继续，注入一个不同的问题
        fork_result = app.invoke(
            {"messages": [HumanMessage(content="分叉后的新问题")]},
            config=fork_config,
        )
        print(f"  分叉后消息数: {len(fork_result['messages'])}")
        for msg in fork_result["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            print(f"    [{role}] {msg.content}")

        # ── 5. 验证原始线程不受影响 ─────────────────────────
        print("\n=== 验证原始线程 ===")
        original_state = app.get_state(config)
        print(f"  原始线程最新消息数: {len(original_state.values['messages'])}")


if __name__ == "__main__":
    main()
