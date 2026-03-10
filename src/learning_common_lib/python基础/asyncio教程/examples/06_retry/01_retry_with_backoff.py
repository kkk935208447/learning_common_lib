"""
目标: 演示指数退避重试策略
关键 API: asyncio.sleep
Python 版本: 3.11+
运行命令: uv run python examples/06_retry/01_retry_with_backoff.py  (从 asyncio教程/ 目录)
预期现象: 前几次调用失败并重试（间隔递增），最终成功或达到最大重试次数
生产提醒: 重试必须有上限，且只重试可恢复错误，不要对参数错误盲目重试
"""

import asyncio
import random

random.seed(42)  # 固定种子，确保输出可复现


class TemporaryError(Exception):
    pass


async def unstable_call() -> str:
    await asyncio.sleep(0.3)
    if random.random() < 0.7:
        raise TemporaryError("temporary failure")
    return "success"


async def retry_with_backoff(
    func,
    retries: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    retry_exceptions: tuple[type[Exception], ...] = (TemporaryError,),
):
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            return await func()
        except retry_exceptions as exc:
            last_exc = exc
            if attempt == retries:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay * 0.2)
            sleep_time = delay + jitter
            print(f"attempt={attempt} failed, retry in {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)

    raise last_exc


async def main() -> None:
    try:
        result = await retry_with_backoff(unstable_call)
        print("result:", result)
    except TemporaryError as exc:
        print("all retries failed:", exc)


if __name__ == "__main__":
    asyncio.run(main())
