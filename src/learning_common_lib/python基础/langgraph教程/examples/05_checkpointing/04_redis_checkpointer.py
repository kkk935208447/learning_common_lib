from __future__ import annotations

"""
目标：使用 Redis 持久化 checkpoint，支持跨进程恢复和 TTL 管理
关键 API：AsyncRedisSaver (from langgraph.checkpoint.redis.aio import AsyncRedisSaver)
运行命令：python 04_redis_checkpointer.py
预期现象：
  1. 连接 Redis 并创建 AsyncRedisSaver
  2. 多轮对话后 checkpoint 持久化到 Redis
  3. 模拟"跨进程恢复"：重新编译图并从 Redis 恢复状态
  4. 输出明确的运行时状态，便于 smoke / 排障判断是否真的用了 Redis
生产提醒：
  - 需要安装: pip install langgraph-checkpoint-redis
  - 需要带 RediSearch/Redis Stack 能力的 Redis 实例，普通 Redis 可能报 `FT._LIST` 不存在
  - Redis 连接需要配置密码和合适的 DB 编号
  - 教程默认让 checkpoint / store 共用 db=0，通过不同 prefix 隔离
  - TTL 策略：通过 Redis 的 EXPIRE 或定期清理过期 checkpoint
"""

import asyncio
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState, StateGraph

try:
    from ...templates import DEFAULT_RUNTIME_SETTINGS
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import DEFAULT_RUNTIME_SETTINGS

# Redis 连接配置
REDIS_URL = DEFAULT_RUNTIME_SETTINGS.checkpoint_url
STRICT_REDIS = DEFAULT_RUNTIME_SETTINGS.strict_redis


def emit_runtime_status(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    line = f"RUNTIME_STATUS checkpoint={backend} degraded={degraded} strict={STRICT_REDIS}"
    if last_error:
        line += f" last_error={last_error}"
    print(line)


def require_real_redis(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    emit_runtime_status(backend=backend, degraded=degraded, last_error=last_error)
    if STRICT_REDIS and (backend != "redis" or degraded):
        raise RuntimeError(
            "Redis checkpoint 示例要求真实 Redis backend；"
            f"当前 backend={backend}, degraded={degraded}, last_error={last_error}"
        )


def chatbot(state: MessagesState) -> dict:
    """聊天节点"""
    msg_count = len(state["messages"])
    return {
        "messages": [
            AIMessage(content=f"Redis checkpoint 演示 - 当前消息数: {msg_count + 1}")
        ]
    }


def build_graph() -> StateGraph:
    """构建图（可复用，模拟跨进程场景）"""
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", chatbot)
    graph.set_entry_point("chatbot")
    return graph


async def open_async_redis_saver(async_redis_saver_cls):
    """重复运行示例时复用现有索引，避免 `Index already exists` 误判为失败。"""
    saver_cm = async_redis_saver_cls.from_conn_string(
        REDIS_URL,
        checkpoint_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_prefix,
        checkpoint_write_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_write_prefix,
    )
    try:
        saver = await saver_cm.__aenter__()
        return saver, saver_cm.__aexit__
    except Exception as exc:
        if "index already exists" not in str(exc).lower():
            raise

        from langgraph.checkpoint.redis.aio import AsyncKeyRegistry

        saver = async_redis_saver_cls(
            redis_url=REDIS_URL,
            checkpoint_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_prefix,
            checkpoint_write_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_write_prefix,
        )
        saver.create_indexes()
        await saver._detect_cluster_mode()
        saver._key_registry = AsyncKeyRegistry(saver._redis)
        await saver.aset_client_info()
        return saver, saver.__aexit__


async def main() -> None:
    run_id = DEFAULT_RUNTIME_SETTINGS.demo_suffix("redis-checkpoint")
    thread_id = DEFAULT_RUNTIME_SETTINGS.global_thread_id("demo", run_id)

    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    except ImportError as exc:
        require_real_redis(
            backend="memory",
            degraded=True,
            last_error=f"ImportError: {exc}",
        )
        print("请先安装: pip install langgraph-checkpoint-redis")
        print("以下使用 MemorySaver 作为降级演示...\n")
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = build_graph()
        app = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        print("=== 降级模式：MemorySaver ===")
        r = app.invoke({"messages": [HumanMessage(content="测试")]}, config=config)
        print(f"  回复: {r['messages'][-1].content}")
        print("\n提示：安装 langgraph-checkpoint-redis 后可体验完整 Redis 功能")
        return

    try:
        checkpointer, close_checkpointer = await open_async_redis_saver(AsyncRedisSaver)
        try:
            require_real_redis(backend="redis", degraded=False)
            print("=== Redis Checkpointer 已连接 ===")
            print(f"thread_id: {thread_id}")

            graph = build_graph()
            app = graph.compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}

            print("\n--- 进程 A：创建对话 ---")
            for msg_text in ["你好", "LangGraph 怎么用？"]:
                result = await app.ainvoke(
                    {"messages": [HumanMessage(content=msg_text)]}, config=config
                )
                print(f"  用户: {msg_text}")
                print(f"  助手: {result['messages'][-1].content}")

            print("\n--- 进程 B：从 Redis 恢复状态 ---")
            graph2 = build_graph()
            app2 = graph2.compile(checkpointer=checkpointer)

            state = await app2.aget_state(config)
            if state and state.values:
                print(f"  恢复成功！消息数: {len(state.values['messages'])}")
                for msg in state.values["messages"]:
                    role = "用户" if isinstance(msg, HumanMessage) else "助手"
                    print(f"    [{role}] {msg.content}")

                result = await app2.ainvoke(
                    {"messages": [HumanMessage(content="继续上次的话题")]}, config=config
                )
                print(f"\n  继续对话后消息数: {len(result['messages'])}")
            else:
                raise RuntimeError("Redis checkpoint 未恢复到任何状态，示例不符合预期")

            print("\n=== DB / Prefix 隔离策略 ===")
            print("  推荐方案：")
            print("  - checkpoint / store 默认共享 DB 0")
            print("  - 通过 checkpoint/store 各自 prefix 隔离 key 空间")
            print("  - cache 或实验数据可单独放到 DB 2")

        finally:
            await close_checkpointer(None, None, None)
            print("\n=== Redis 连接已关闭 ===")
    except Exception as exc:
        require_real_redis(
            backend="memory",
            degraded=True,
            last_error=f"{type(exc).__name__}: {exc}",
        )
        print(f"Redis 不可用，降级到 MemorySaver: {type(exc).__name__}: {exc}")
        if "FT._LIST" in str(exc):
            print("提示: 当前 Redis 缺少 RediSearch/Redis Stack 能力，无法使用 langgraph-checkpoint-redis")
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = build_graph()
        app = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        result = await app.ainvoke(
            {"messages": [HumanMessage(content="Redis 不可用时如何处理？")]},
            config=config,
        )
        print(f"  降级模式回复: {result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(main())
