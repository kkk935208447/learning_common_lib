"""
目标: 演示 except* 语法和与 asyncio.TaskGroup 的配合
关键 API: except*, asyncio.TaskGroup, ExceptionGroup
Python 版本: 3.11+
运行命令: uv run python examples/06_exception_group/02_except_star.py  (从 exception教程/ 目录)
预期现象: 展示 except* 如何选择性捕获 ExceptionGroup 中的特定类型
生产提醒: except* 是处理并发任务异常的标准方式，但要注意它不能和普通 except 混用在同一个 try 块中
"""

import asyncio


# ============================================================
# 1. except* 基本语法
# ============================================================
def demo_basic_except_star():
    print("=" * 60)
    print("1. except* 基本语法")
    print("=" * 60)

    try:
        raise ExceptionGroup("errors", [
            ValueError("bad value"),
            TypeError("bad type"),
            OSError("disk full"),
        ])
    except* ValueError as eg:
        print(f"  caught ValueError group: {eg.exceptions}")
    except* (TypeError, OSError) as eg:
        print(f"  caught Type/OS group: {eg.exceptions}")


# ============================================================
# 2. except* 的关键特性
# ============================================================
def demo_multiple_match():
    print("\n" + "=" * 60)
    print("2. except* 多个分支可以同时匹配")
    print("=" * 60)

    # 关键区别：普通 except 只匹配第一个，except* 可以同时匹配多个
    handled_types = []

    try:
        raise ExceptionGroup("errors", [
            ValueError("val-1"),
            ValueError("val-2"),
            TypeError("type-1"),
        ])
    except* ValueError as eg:
        handled_types.append("ValueError")
        print(f"  ValueError 分支: 捕获 {len(eg.exceptions)} 个")
        for exc in eg.exceptions:
            print(f"    - {exc}")
    except* TypeError as eg:
        handled_types.append("TypeError")
        print(f"  TypeError 分支: 捕获 {len(eg.exceptions)} 个")
        for exc in eg.exceptions:
            print(f"    - {exc}")

    print(f"\n  两个分支都被执行了: {handled_types}")


# ============================================================
# 2b. 未匹配的异常会继续传播
# ============================================================
def demo_unmatched_propagation():
    print("\n" + "=" * 60)
    print("2b. 未匹配的异常继续传播")
    print("=" * 60)

    try:
        try:
            raise ExceptionGroup("errors", [
                ValueError("handled"),
                RuntimeError("not handled"),
            ])
        except* ValueError as eg:
            print(f"  内层捕获 ValueError: {eg.exceptions}")
            # RuntimeError 没有匹配的 except*，会继续传播
    except ExceptionGroup as eg:
        print(f"  外层捕获未处理的异常组: {eg}")
        for exc in eg.exceptions:
            print(f"    - {type(exc).__name__}: {exc}")


# ============================================================
# 3. 与 asyncio.TaskGroup 配合
# ============================================================
async def task_ok():
    """正常完成的任务。"""
    await asyncio.sleep(0.01)
    return "ok"


async def task_value_error():
    """抛出 ValueError 的任务。"""
    await asyncio.sleep(0.01)
    raise ValueError("bad value")


async def task_type_error():
    """抛出 TypeError 的任务。"""
    await asyncio.sleep(0.01)
    raise TypeError("bad type")


async def demo_taskgroup():
    print("\n" + "=" * 60)
    print("3. except* 与 asyncio.TaskGroup 配合")
    print("=" * 60)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(task_ok())
            tg.create_task(task_value_error())
            tg.create_task(task_type_error())
    except* ValueError as eg:
        print(f"  ValueError 分支: {eg.exceptions}")
    except* TypeError as eg:
        print(f"  TypeError 分支: {eg.exceptions}")

    print("  TaskGroup 中的异常被 except* 分类处理完毕")


# ============================================================
# 3b. TaskGroup 中多个同类型异常
# ============================================================
async def task_conn_error(host):
    """模拟连接失败。"""
    await asyncio.sleep(0.01)
    raise ConnectionError(f"无法连接 {host}")


async def demo_taskgroup_same_type():
    print("\n" + "=" * 60)
    print("3b. TaskGroup 中多个同类型异常")
    print("=" * 60)

    hosts = ["db-1.example.com", "db-2.example.com", "db-3.example.com"]
    try:
        async with asyncio.TaskGroup() as tg:
            for host in hosts:
                tg.create_task(task_conn_error(host))
    except* ConnectionError as eg:
        print(f"  捕获 {len(eg.exceptions)} 个 ConnectionError:")
        for exc in eg.exceptions:
            print(f"    - {exc}")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    demo_basic_except_star()
    demo_multiple_match()
    demo_unmatched_propagation()
    asyncio.run(demo_taskgroup())
    asyncio.run(demo_taskgroup_same_type())
    print("\n" + "=" * 60)
    print("全部演示完成")
    print("=" * 60)