"""
目标: Chord 和 Chunks 工作流 — 并行计算+回调聚合、批量分块处理
关键 API: chord(), chunks(), group(), callback
Python 版本: 3.11+
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.09_workflows.02_chord_and_chunks worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/09_workflows/02_chord_and_chunks.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: 演示 chord 并行+回调、chunks 分块处理、错误处理
生产提醒: chord 依赖 result backend；chord 中任一任务失败会触发 chord_error 而非 callback
"""

from __future__ import annotations

import asyncio

from celery import Celery, chord, group

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.09_workflows.02_chord_and_chunks",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 定义任务 ──
@app.task
def square(n: int) -> int:
    """计算平方"""
    result = n * n
    print(f"  🔢 square({n}) = {result}")
    return result


@app.task
def cube(n: int) -> int:
    """计算立方"""
    result = n * n * n
    print(f"  🔢 cube({n}) = {result}")
    return result


@app.task
def sum_results(results: list) -> int:
    """聚合求和 — chord 的 callback。

    注意: chord 传入的 results 可能是嵌套列表（每个 group 成员的结果），
    需要展平后求和。
    """
    # 展平可能的嵌套列表
    flat: list[int] = []
    for item in results:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    total = sum(flat)
    print(f"  📊 sum({flat}) = {total}")
    return total


@app.task
def count_results(results: list) -> str:
    """统计分块处理结果数量 — chunks+chord 的 callback"""
    flat: list = []
    for item in results:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    report = f"共处理 {len(flat)} 个条目"
    print(f"  📊 {report}")
    return report


@app.task
def process_item(item: str) -> str:
    """处理单个条目"""
    result = f"processed_{item}"
    print(f"  ⚙️ 处理: {item} → {result}")
    return result


@app.task
def process_chunk(items: list[tuple[str]]) -> list[str]:
    """处理一个分块 — chunks 会将参数打包成 list[tuple]"""
    results = []
    for args in items:
        item = args[0] if isinstance(args, (list, tuple)) else args
        result = f"processed_{item}"
        results.append(result)
    print(f"  📦 分块处理: {len(items)} 个条目")
    return results


@app.task
def failing_square(n: int) -> int:
    """故意失败的任务"""
    if n == 3:
        raise ValueError(f"无法处理 n={n}")
    return n * n


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 Celery Chord & Chunks 工作流示例\n")

    # ── Chord: 并行计算 + 回调聚合 ──
    print("── Chord: 并行求平方 → 求和 ──")
    # chord(header, callback): header 全部完成后，结果列表传给 callback
    numbers = [1, 2, 3, 4, 5]
    c = chord(
        group(square.s(n) for n in numbers),  # header: 并行计算
        sum_results.s(),                       # callback: 聚合结果
    )
    result = await asyncio.to_thread(c.apply_async)
    print(f"  ✅ Chord 结果: {await asyncio.to_thread(result.get, timeout=30)}")
    print(f"  💡 1²+2²+3²+4²+5² = 1+4+9+16+25 = 55\n")

    # ── Chord 链式: chord → chain ──
    print("── Chord + Chain: 并行求立方 → 求和 → 报告 ──")
    c2 = chord(
        group(cube.s(n) for n in [1, 2, 3]),
        sum_results.s(),  # callback 接收结果列表
    )
    result2 = await asyncio.to_thread(c2.apply_async)
    print(f"  ✅ Chord+Chain 结果: {await asyncio.to_thread(result2.get, timeout=30)}")
    print(f"  💡 1³+2³+3³ = 1+8+27 = 36\n")

    # ── Chunks: 批量分块处理 ──
    print("── Chunks: 批量分块处理 ──")
    items = [f"item_{i}" for i in range(10)]
    # chunks(items, chunk_size) 将任务参数分成多个组
    # 每个 chunk 作为一个独立任务执行
    chunked = process_item.chunks(
        [(item,) for item in items],  # 参数列表，每个元素是一个 args tuple
        3,                             # 每块 3 个
    )
    print(f"  📋 总条目: {len(items)}, 分块大小: 3, 预计分块数: 4")
    chunk_result = await asyncio.to_thread(chunked.apply_async)
    all_results = await asyncio.to_thread(chunk_result.get, timeout=30)
    print(f"  ✅ Chunks 结果 ({len(all_results)} 个分块):")
    for i, chunk in enumerate(all_results):
        print(f"     分块 {i}: {chunk}")
    print()

    # ── Chunks + Chord: 分块处理 + 聚合 ──
    print("── Chunks as Group (用于 Chord) ──")
    # .group() 将 chunks 转为 group，可用于 chord
    chunked_group = process_item.chunks(
        [(f"order_{i}",) for i in range(6)],
        2,
    ).group()
    c3 = chord(
        chunked_group,
        count_results.s(),  # 接收每个 chunk 的结果列表
    )
    result3 = await asyncio.to_thread(c3.apply_async)
    print(f"  ✅ Chunks+Chord 结果: {await asyncio.to_thread(result3.get, timeout=30)}\n")

    # ── Chord 错误处理 ──
    print("── Chord 错误处理 ──")
    print("  💡 chord 中任一 header 任务失败 → callback 不执行")
    print("  💡 可通过 link_error 捕获错误:")
    print("     chord(header)(callback, link_error=error_handler.s())")
    print()

    try:
        c4 = chord(
            group(failing_square.s(n) for n in [1, 2, 3, 4]),
            sum_results.s(),
        )
        result4 = await asyncio.to_thread(c4.apply_async)
        await asyncio.to_thread(result4.get, timeout=30)
    except Exception as e:
        print(f"  ❌ Chord 失败: {e}")
        print("  💡 n=3 时任务抛出异常，callback (sum_results) 未执行")


if __name__ == "__main__":
    asyncio.run(main())
