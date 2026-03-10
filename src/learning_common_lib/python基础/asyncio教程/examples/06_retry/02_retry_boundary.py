"""
目标: 演示重试边界 —— 哪些错误应该重试，哪些绝对不能重试
关键 API: asyncio.sleep (退避等待), 自定义异常层次
Python 版本: 3.11+
运行命令: uv run python examples/06_retry/02_retry_boundary.py  (从 asyncio教程/ 目录)
预期现象: TransientError 被重试直到成功，PermanentError 立即传播不重试
生产提醒: 永远不要对参数错误、权限错误、404 等不可恢复错误做重试
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


# ── 异常层次 ──────────────────────────────────────────────

class TransientError(Exception):
    """可恢复的瞬时错误（网络抖动、限流等）。"""


class PermanentError(Exception):
    """不可恢复的永久错误（认证失败、参数错误等）。"""


# ── 带重试边界的重试器 ────────────────────────────────────

async def retry_with_boundary(
    func: Callable[..., Coroutine[Any, Any, str]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> str:
    """只对 TransientError 重试，PermanentError 立即传播。"""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [retry] 第 {attempt} 次尝试 ...")
            result: str = await func(*args)
            print(f"  [retry] 成功: {result}")
            return result
        except TransientError as e:
            print(f"  [retry] TransientError: {e}")
            if attempt == max_retries:
                print(f"  [retry] 已达最大重试次数 ({max_retries})，放弃")
                raise
            wait: float = base_delay * attempt
            print(f"  [retry] 等待 {wait}s 后重试 ...")
            await asyncio.sleep(wait)
        except PermanentError:
            print(f"  [retry] PermanentError 不可重试，立即传播!")
            raise

    # 不应到达这里，但为了类型安全
    raise RuntimeError("unreachable")


# ── 模拟业务函数 ──────────────────────────────────────────

def make_flaky_call(error_sequence: list[Exception | None]) -> Callable[[], Coroutine[Any, Any, str]]:
    """创建一个按预定序列抛出异常的函数（确定性，非随机）。"""
    call_count: int = 0

    async def call() -> str:
        nonlocal call_count
        error = error_sequence[call_count] if call_count < len(error_sequence) else None
        call_count += 1
        if error is not None:
            raise error
        return "请求成功"

    return call


# ── 主流程 ────────────────────────────────────────────────

async def main() -> None:
    print("=== 重试边界演示 ===\n")

    # 场景 1: TransientError -> TransientError -> 成功
    print("场景 1: 两次瞬时错误后成功")
    print("-" * 40)
    flaky_ok = make_flaky_call([
        TransientError("连接超时"),
        TransientError("服务限流"),
        None,  # 第 3 次成功
    ])
    result = await retry_with_boundary(flaky_ok)
    print(f"  最终结果: {result}\n")

    # 场景 2: PermanentError 立即传播
    print("场景 2: 永久错误，不重试")
    print("-" * 40)
    flaky_perm = make_flaky_call([
        PermanentError("认证令牌无效 (401)"),
    ])
    try:
        await retry_with_boundary(flaky_perm)
    except PermanentError as e:
        print(f"  捕获 PermanentError: {e}")
        print("  没有进行任何重试 —— 这是正确行为。\n")

    print("结论: 重试边界是重试策略的第一道防线，错误分类决定是否重试。")


if __name__ == "__main__":
    asyncio.run(main())
