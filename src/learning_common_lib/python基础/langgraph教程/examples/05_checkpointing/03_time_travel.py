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
    4. 分叉线程与原始线程各自保留独立的最新头

生产提醒:
    - get_state_history 返回的是倒序列表（最新在前）
    - history 里可能出现“相同消息数”的多个 checkpoint，这是正常的
      因为同一次用户交互通常会留下 `source=input` 和 `source=loop` 两类快照
    - 如果你想真正“分叉出一条新线”，应使用新的 `thread_id`，
      并把历史快照的业务状态复制到新线程
    - 只传历史 `checkpoint_id` 而继续沿用原 `thread_id`，会把原线程头推进到新分支
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
    original_config = {"configurable": {"thread_id": "time-travel-demo"}}

    # ── 1. 进行多轮对话，积累 checkpoint ────────────────────
    print("=== 多轮对话 ===")
    questions = ["第一个问题", "第二个问题", "第三个问题"]
    for q in questions:
        result = app.invoke({"messages": [HumanMessage(content=q)]}, config=original_config)
        print(f"  用户: {q}")
        print(f"  助手: {result['messages'][-1].content}")

    # ── 2. 列出所有历史 checkpoint ──────────────────────────
    print("\n=== 历史 Checkpoint 列表（最新在前）===")
    history = list(app.get_state_history(original_config))
    for i, state_snapshot in enumerate(history):
        cp_id = state_snapshot.config["configurable"].get("checkpoint_id", "N/A")
        msg_count = len(state_snapshot.values.get("messages", []))
        source = state_snapshot.metadata.get("source", "unknown")
        step = state_snapshot.metadata.get("step", "N/A")
        print(
            f"  [{i}] checkpoint_id={cp_id[:20]}... "
            f"消息数={msg_count} source={source} step={step}"
        )

    # ── 3. 回溯到第一轮对话后的状态 ─────────────────────────
    # history 是倒序的，最后一个元素是最早的状态。
    # 注意：同样的消息数可能出现两次，例如：
    # - source=input：用户消息刚写入，还没经过节点执行
    # - source=loop：节点执行完成后的快照
    #
    # 这里我们要找的是“第一轮对话已经完成”的状态，所以选择：
    # - 消息数 = 2
    # - source = loop
    target_snapshot = None
    for snap in history:
        if (
            len(snap.values.get("messages", [])) == 2
            and snap.metadata.get("source") == "loop"
        ):
            target_snapshot = snap
            break

    if target_snapshot:
        target_cp_id = target_snapshot.config["configurable"]["checkpoint_id"]
        print(f"\n=== 回溯到 checkpoint: {target_cp_id[:20]}... ===")
        print(
            "  选择理由: 这是第一轮完成后的 loop 快照，"
            "而不是用户消息刚写入但节点尚未执行的 input 快照"
        )
        print(f"  该时刻的消息:")
        for msg in target_snapshot.values["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            # print(f"    [{role}] {msg.content}")
            print(f"    [{role}] {msg}")

        # ── 4. 从历史点分叉执行 ─────────────────────────────
        print("\n=== 从历史点分叉 ===")
        # 真正的“分叉”应该：
        # 1. 使用新的 thread_id
        # 2. 把历史快照中的业务状态复制到新线程
        #
        # 如果只是把 checkpoint_id 和新的 thread_id 一起传给 invoke，
        # 并不会自动继承旧线程里的 state。
        fork_config = {
            "configurable": {
                "thread_id": "time-travel-demo-fork",
            }
        }
        app.update_state(
            fork_config,
            {"messages": target_snapshot.values["messages"]},
        )

        # 从复制出来的历史状态继续，注入一个不同的问题，形成新的 fork 线程
        fork_result = app.invoke(
            {"messages": [HumanMessage(content="分叉后的新问题")]},
            config=fork_config,
        )
        print(f"  分叉后消息数: {len(fork_result['messages'])}")
        for msg in fork_result["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            # print(f"    [{role}] {msg.content}")
            print(f"    [{role}] {msg}")

        # ── 5. 验证原始线程不受影响 ─────────────────────────
        print("\n=== 验证原始线程 ===")
        original_state = app.get_state(original_config)
        curr_ck_id = original_state.config["configurable"].get("checkpoint_id", "N/A")
        print(f"  原始线程 checkpoint id: {curr_ck_id[:20]}...")
        for msg in original_state.values["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            # print(f"    [{role}] {msg.content}")
            print(f"    [{role}] {msg}")

        print("\n=== 查看分叉线程 ===")
        fork_state = app.get_state(fork_config)
        fork_ck_id = fork_state.config["configurable"].get("checkpoint_id", "N/A")
        print(f"  分叉线程 checkpoint id: {fork_ck_id[:20]}...")
        for msg in fork_state.values["messages"]:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            # print(f"    [{role}] {msg.content}")
            print(f"    [{role}] {msg}")


if __name__ == "__main__":
    main()
