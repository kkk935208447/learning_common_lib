"""
目标: Chain 和 Group 工作流 — 串行链式调用与并行分组执行
关键 API: chain(), group(), .s(), .si(), | 操作符
Python 版本: 3.11+
运行命令:
  终端 1 (启动 Worker):
    celery -A examples.08_workflows.01_chain_and_group worker -l info -P solo
  终端 2 (运行示例):
    uv run python examples/08_workflows/01_chain_and_group.py
  (从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录)
预期现象: 演示 chain 结果传递、group 并行执行、组合使用
生产提醒: chain 中任一任务失败会中断后续任务；group 中单个失败不影响其他任务
"""

from __future__ import annotations

import asyncio

from celery import Celery, chain, group

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.08_workflows.01_chain_and_group",
    broker="redis://:123456@localhost:6379/0",
    backend="redis://:123456@localhost:6379/1",
)


# ── 2. 定义任务 ──
@app.task
def fetch_data(source: str) -> dict[str, str]:
    """获取数据"""
    print(f"  📥 获取数据: source={source}")
    return {"source": source, "rows": "1000"}


@app.task
def transform(data: dict[str, str]) -> dict[str, str]:
    """转换数据 — 接收上一步结果"""
    print(f"  🔄 转换数据: {data}")
    data["transformed"] = "true"
    data["rows"] = str(int(data["rows"]) - 50)  # 过滤掉 50 行
    return data


@app.task
def load(data: dict[str, str]) -> str:
    """加载数据 — 接收上一步结果"""
    print(f"  📤 加载数据: {data}")
    return f"loaded_{data['rows']}_rows_from_{data['source']}"


@app.task
def add(x: int, y: int) -> int:
    print(f"  ➕ {x} + {y} = {x + y}")
    return x + y


@app.task
def multiply(x: int, y: int) -> int:
    print(f"  ✖️ {x} × {y} = {x * y}")
    return x * y


@app.task
def aggregate(results: list[int]) -> dict[str, int]:
    """聚合多个结果"""
    total = sum(results)
    print(f"  📊 聚合: {results} → 总和={total}")
    return {"results": results, "total": total}


@app.task
def failing_task(x: int) -> int:
    """故意失败的任务"""
    raise ValueError(f"任务失败: x={x}")


# ── 3. 入口 ──
async def main() -> None:
    print("🚀 Celery Chain & Group 工作流示例\n")

    # ── Chain: 串行链式调用 ──
    print("── Chain: ETL 管道 (fetch → transform → load) ──")
    # .s() 创建 signature，chain 中上一步的返回值自动作为下一步的第一个参数
    etl_chain = chain(
        fetch_data.s("mysql_orders"),
        transform.s(),
        load.s(),
    )
    result = await asyncio.to_thread(etl_chain.apply_async)
    print(f"  ✅ Chain 最终结果: {await asyncio.to_thread(result.get, timeout=30)}\n")

    # Chain 也可以用 | 操作符
    print("── Chain: 使用 | 操作符 ──")
    pipe = fetch_data.s("postgresql_users") | transform.s() | load.s()
    result2 = await asyncio.to_thread(pipe.apply_async)
    print(f"  ✅ Pipe 最终结果: {await asyncio.to_thread(result2.get, timeout=30)}\n")

    # ── Group: 并行分组执行 ──
    print("── Group: 并行计算 ──")
    calc_group = group(
        add.s(1, 2),
        add.s(3, 4),
        multiply.s(5, 6),
        multiply.s(7, 8),
    )
    group_result = await asyncio.to_thread(calc_group.apply_async)
    results = await asyncio.to_thread(group_result.get, timeout=30)
    print(f"  ✅ Group 结果列表: {results}\n")

    # ── .s() vs .si() ──
    print("── .s() vs .si(): immutable signature ──")
    # .si() = immutable signature，不接收上一步的返回值
    immutable_chain = chain(
        add.s(10, 20),       # 返回 30
        multiply.si(3, 4),   # .si() 忽略上一步的 30，直接用 (3, 4)
    )
    r3 = await asyncio.to_thread(immutable_chain.apply_async)
    print(f"  ✅ .si() 结果: {await asyncio.to_thread(r3.get, timeout=30)} (3×4=12，忽略了上一步的 30)\n")

    # ── Chain + Group 组合 ──
    print("── Chain + Group 组合 ──")
    # 先并行计算，再聚合
    workflow = chain(
        group(
            add.s(10, 20),
            add.s(30, 40),
            multiply.s(2, 5),
        ),
        aggregate.s(),  # 接收 group 的结果列表
    )
    r4 = await asyncio.to_thread(workflow.apply_async)
    print(f"  ✅ 组合结果: {await asyncio.to_thread(r4.get, timeout=30)}\n")

    # ── Chain 错误传播 ──
    print("── Chain 错误传播 ──")
    error_chain = chain(
        add.s(1, 2),
        failing_task.s(),  # 这里会失败
        add.s(100),        # 不会执行
    )
    try:
        r5 = await asyncio.to_thread(error_chain.apply_async)
        await asyncio.to_thread(r5.get, timeout=30)
    except Exception as e:
        print(f"  ❌ Chain 中断: {e}")
        print("  💡 chain 中任一任务失败，后续任务不会执行")


if __name__ == "__main__":
    asyncio.run(main())
