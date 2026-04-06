"""
05_checkpointing / 04_redis_checkpointer

目标:
    使用 Redis 持久化 checkpoint，支持跨进程恢复和 TTL 管理

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    AsyncRedisSaver (from langgraph.checkpoint.redis.aio import AsyncRedisSaver)

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/05_checkpointing/04_redis_checkpointer.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        env LANGGRAPH_STRICT_REDIS=1 uv run python examples/05_checkpointing/04_redis_checkpointer.py

预期现象:
    1. 连接 Redis 并创建 AsyncRedisSaver
    2. 多轮对话后 checkpoint 持久化到 Redis
    3. 模拟"跨进程恢复"：重新编译图并从 Redis 恢复状态
    4. 输出明确的运行时状态，便于 smoke / 排障判断是否真的用了 Redis

LangGraph Redis Checkpointer 相关数据一览
| 名称 / 前缀 | 类型（常见） | 作用 |
|-------------|--------------|------|
| `lg_tutorial_cp` | RediSearch 索引（checkpoint 前缀可配置） | 索引各条 **checkpoint** 的 JSON 键，供 `FT.SEARCH` 等查询与恢复状态 |
| `lg_tutorial_cp_writes` | RediSearch 索引（writes 前缀可配置） | 索引各条 **channel write** 记录，与 checkpoint 配合还原中间写入 |
| `checkpoint_latest` | 字符串键 `checkpoint_latest:{thread}:{ns}` | **最新 checkpoint 指针**，值为当前最新 checkpoint 对应 Redis 键，便于快速定位 |
| `write_keys_zset` | 有序集合键 `write_keys_zset:{thread}:{ns}:{checkpoint_id}` | 每个 checkpoint 下登记相关 **write 键**，用 ZSET 顺序加速查找，减少对搜索的依赖 |
默认前缀来自教程里的 `checkpoint_prefix` / `checkpoint_write_prefix` 参数。

生产提醒:
    - 需要安装: pip install langgraph-checkpoint-redis
    - 需要带 RediSearch/Redis Stack 能力的 Redis 实例，普通 Redis 可能报 `FT._LIST` 不存在
    - Redis 连接需要配置密码和合适的 DB 编号
    - 教程默认让 checkpoint / store 共用 db=0，通过不同 prefix 隔离
    - TTL 策略：通过 Redis 的 EXPIRE 或定期清理过期 checkpoint
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState, StateGraph

try:
    from ...templates import DEFAULT_RUNTIME_SETTINGS
except ImportError:  # pragma: no cover - 允许直接运行脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from templates import DEFAULT_RUNTIME_SETTINGS

if TYPE_CHECKING:
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

# Redis 连接配置
REDIS_URL = DEFAULT_RUNTIME_SETTINGS.checkpoint_url
STRICT_REDIS = DEFAULT_RUNTIME_SETTINGS.strict_redis


def emit_runtime_status(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    """输出运行时状态，便于 smoke / 排障判断是否真的用了 Redis"""
    line = f"RUNTIME_STATUS checkpoint={backend} degraded={degraded} strict={STRICT_REDIS}"
    if last_error:
        line += f" last_error={last_error}"
    print(line)


def require_real_redis(*, backend: str, degraded: bool, last_error: str | None = None) -> None:
    """要求 Redis 连接正常，否则抛出异常"""
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


def _is_existing_index_error(exc: Exception) -> bool:
    return "index already exists" in str(exc).lower()


async def _close_failed_saver(saver: Any, exc: BaseException | None = None) -> None:
    try:
        await saver.__aexit__(
            type(exc) if exc is not None else None,
            exc,
            exc.__traceback__ if exc is not None else None,
        )
    except Exception:
        # 教学示例里不额外中断主流程，关闭失败只作为调试辅助信息。
        print("[debug] 关闭失败的 Redis saver 时再次出错")


async def _create_index_allow_existing(index: Any) -> None:
    try:
        await index.create(overwrite=False)
    except Exception as exc:
        if not _is_existing_index_error(exc):
            raise


async def open_async_redis_saver(async_redis_saver_cls: type["AsyncRedisSaver"]):
    """重复运行示例时复用/补齐已存在的索引，并保证失败路径会释放连接。"""
    saver = async_redis_saver_cls(
        redis_url=REDIS_URL,
        checkpoint_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_prefix,
        checkpoint_write_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_write_prefix,
    )
    try:
        saver = await saver.__aenter__()
        return saver, saver.__aexit__   # 返回 saver 实例和 __aexit__ 方法
    except Exception as exc:
        await _close_failed_saver(saver, exc)
        if not _is_existing_index_error(exc):
            raise

        from langgraph.checkpoint.redis.aio import AsyncKeyRegistry

        # 索引已存在：不要直接假设两个索引都齐全，而是逐个 create；
        # 已存在则忽略，缺失则补齐。然后再复刻 asetup()/__aenter__ 的剩余初始化步骤。
        saver = async_redis_saver_cls(
            redis_url=REDIS_URL,
            checkpoint_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_prefix,
            checkpoint_write_prefix=DEFAULT_RUNTIME_SETTINGS.checkpoint_write_prefix,
        )
        try:
            await _create_index_allow_existing(saver.checkpoints_index)
            await _create_index_allow_existing(saver.checkpoint_writes_index)
            await saver._detect_cluster_mode()
            saver._key_registry = AsyncKeyRegistry(saver._redis)
            await saver.aset_client_info()
            return saver, saver.__aexit__   # 返回 saver 实例和 __aexit__ 方法
        except Exception as fallback_exc:
            await _close_failed_saver(saver, fallback_exc)
            raise


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
        # close_checkpointer 即 __aexit__；正常结束时传入 (None, None, None) 表示是 __aexit__(exc_type, exc, tb)，三个 None 表示无异常、正常收尾。
        checkpointer, close_checkpointer = await open_async_redis_saver(AsyncRedisSaver)
        try:
            require_real_redis(backend="redis", degraded=False)
            print("=== Redis Checkpointer 已连接 ===")
            print(f"thread_id: {thread_id}")

            graph = build_graph()
            # 同一 checkpointer 实例：checkpoint 读写都落在同一 Redis key 前缀与 thread_id 上
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
            # 新编译的图 + 同一 checkpointer：模拟另一进程只凭 thread_id 从 Redis 拉状态
            graph2 = build_graph()
            app2 = graph2.compile(checkpointer=checkpointer)

            state = await app2.aget_state(config)
            if state and state.values:
                print(f"  恢复成功！消息数: {len(state.values['messages'])}")
                for msg in state.values["messages"]:
                    role = "用户" if isinstance(msg, HumanMessage) else "助手"
                    # print(f"    [{role}] {msg.content}")
                    print(f"    [{role}] {msg}")

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
            # 调用异步上下文管理器的 __aexit__(exc_type, exc, tb)；三个 None 表示正常收尾
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
