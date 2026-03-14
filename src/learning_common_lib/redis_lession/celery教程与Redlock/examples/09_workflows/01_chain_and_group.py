"""
目标: 演示工作流编排模式：链式串行与分组并行 (Workflow Orchestration: Chain & Group Patterns)
关键概念:
  - Chain 链式工作流：任务串行执行，前一个任务的结果作为后一个任务的输入
  - Group 分组并行：多个任务并行执行，互不依赖，提高处理效率
  - Signature 任务签名：.s() 创建不可变签名，.si() 忽略前置结果
关键 API: chain(), group(), .s(), .si(), | 操作符
目录导航:
  - 从项目根目录: cd src/learning_common_lib/redis_lession/celery教程与Redlock
  - 从上级目录: cd examples/09_workflows
运行方式:
  Worker: celery -A examples.09_workflows.01_chain_and_group worker -l info -P solo
    (-P solo 使用单线程池，便于观察执行顺序)
  Client: python examples/09_workflows/01_chain_and_group.py
    (演示各种工作流组合模式)
预期现象:
  - Chain 任务按顺序执行，每个任务接收前一个的结果
  - Group 任务并行执行，同时开始处理
  - 组合工作流展示复杂的编排逻辑
生产提醒:
  - Chain 中任一任务失败会中断整个链，需要合理的错误处理
  - Group 中单个任务失败不影响其他任务，但需要检查整体结果
技术要点:
  - .s() 保留参数，.si() 忽略链式传递的结果
  - | 操作符等价于 chain() 函数
  - 工作流可以嵌套组合，实现复杂的业务逻辑
"""

from __future__ import annotations

import asyncio

from celery import Celery, chain, group

# ── 1. 创建 Celery 应用 ──
app = Celery(
    "examples.09_workflows.01_chain_and_group",
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
