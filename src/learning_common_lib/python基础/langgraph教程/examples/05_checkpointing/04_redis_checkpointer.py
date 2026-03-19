from __future__ import annotations

"""
目标：使用 Redis 持久化 checkpoint，支持跨进程恢复和 TTL 管理
关键 API：AsyncRedisSaver (from langgraph.checkpoint.redis.aio import AsyncRedisSaver)
运行命令：python 04_redis_checkpointer.py
预期现象：
  1. 连接 Redis 并创建 AsyncRedisSaver
  2. 多轮对话后 checkpoint 持久化到 Redis
  3. 模拟"跨进程恢复"：重新编译图并从 Redis 恢复状态
  4. ResilientCheckpointer 包装器演示：写入失败时降级为日志
生产提醒：
  - 需要安装: pip install langgraph-checkpoint-redis
  - Redis 连接需要配置密码和合适的 DB 编号
  - 建议为不同环境（dev/staging/prod）使用不同的 DB 编号
  - TTL 策略：通过 Redis 的 EXPIRE 或定期清理过期 checkpoint
"""

import asyncio
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState, StateGraph

logger = logging.getLogger(__name__)

# Redis 连接配置
REDIS_URL = "redis://:123456@localhost:6379/0"


# ── 1. ResilientCheckpointer 包装器 ─────────────────────────
class ResilientCheckpointer:
    """包装 checkpointer，写入失败时降级为仅日志，不阻塞主流程"""

    def __init__(self, underlying: object) -> None:
        self._underlying = underlying

    async def aput(self, config: dict, checkpoint: dict, metadata: dict) -> dict:
        try:
            return await self._underlying.aput(config, checkpoint, metadata)
        except Exception as e:
            logger.error(f"Checkpoint 写入失败，继续执行: {e}")
            return config

    async def aget(self, config: dict) -> dict | None:
        try:
            return await self._underlying.aget(config)
        except Exception as e:
            logger.error(f"Checkpoint 读取失败: {e}")
            return None

    # 代理其他方法到底层 checkpointer
    def __getattr__(self, name: str) -> object:
        return getattr(self._underlying, name)


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


async def main() -> None:
    # ── 2. 连接 Redis 并创建 checkpointer ───────────────────
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    except ImportError:
        print("请先安装: pip install langgraph-checkpoint-redis")
        print("以下使用 MemorySaver 作为降级演示...\n")
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        graph = build_graph()
        app = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "redis-demo-fallback"}}

        print("=== 降级模式：MemorySaver ===")
        r = app.invoke({"messages": [HumanMessage(content="测试")]}, config=config)
        print(f"  回复: {r['messages'][-1].content}")
        print("\n提示：安装 langgraph-checkpoint-redis 后可体验完整 Redis 功能")
        return

    # 使用 async context manager 管理 Redis 连接
    async with AsyncRedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        print("=== Redis Checkpointer 已连接 ===")

        # ── 3. 第一个"进程"：创建对话 ───────────────────────
        graph = build_graph()
        app = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "redis-thread-001"}}

        print("\n--- 进程 A：创建对话 ---")
        for msg_text in ["你好", "LangGraph 怎么用？"]:
            result = await app.ainvoke(
                {"messages": [HumanMessage(content=msg_text)]}, config=config
            )
            print(f"  用户: {msg_text}")
            print(f"  助手: {result['messages'][-1].content}")

        # ── 4. 模拟"跨进程恢复" ─────────────────────────────
        print("\n--- 进程 B：从 Redis 恢复状态 ---")
        # 重新构建图（模拟新进程）
        graph2 = build_graph()
        app2 = graph2.compile(checkpointer=checkpointer)

        # 使用相同的 thread_id 恢复
        state = await app2.aget_state(config)
        if state and state.values:
            print(f"  恢复成功！消息数: {len(state.values['messages'])}")
            for msg in state.values["messages"]:
                role = "用户" if isinstance(msg, HumanMessage) else "助手"
                print(f"    [{role}] {msg.content}")

            # 继续对话
            result = await app2.ainvoke(
                {"messages": [HumanMessage(content="继续上次的话题")]}, config=config
            )
            print(f"\n  继续对话后消息数: {len(result['messages'])}")

        # ── 5. DB 隔离策略说明 ──────────────────────────────
        print("\n=== DB 隔离策略 ===")
        print("  推荐方案：")
        print("  - DB 0: 开发环境 checkpoint")
        print("  - DB 1: 测试环境 checkpoint")
        print("  - DB 2: 生产环境 checkpoint")
        print("  - 或通过 key prefix 隔离: env:prod:thread:{id}")

    print("\n=== Redis 连接已关闭 ===")


if __name__ == "__main__":
    asyncio.run(main())
