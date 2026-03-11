"""
目标: 演示 ExceptionGroup 的创建、遍历和嵌套
关键 API: ExceptionGroup, BaseExceptionGroup, .exceptions, .subgroup, .split
Python 版本: 3.11+
运行命令: uv run python examples/06_exception_group/01_exception_group_basics.py  (从 exception教程/ 目录)
预期现象: 展示 ExceptionGroup 的结构和遍历方式
生产提醒: ExceptionGroup 是 Python 3.11 的重要新特性，asyncio.TaskGroup 失败时就会抛出 ExceptionGroup
"""

import traceback


# ============================================================
# 1. 创建一个简单的 ExceptionGroup
# ============================================================
def demo_create():
    print("=" * 60)
    print("1. 创建 ExceptionGroup")
    print("=" * 60)

    eg = ExceptionGroup("batch errors", [
        ValueError("invalid input"),
        TypeError("wrong type"),
        ConnectionError("network down"),
    ])

    print(f"  类型: {type(eg).__name__}")
    print(f"  消息: {eg.args[0]}")
    print(f"  包含 {len(eg.exceptions)} 个异常")


# ============================================================
# 2. 遍历 .exceptions 属性
# ============================================================
def demo_iterate():
    print("\n" + "=" * 60)
    print("2. 遍历 .exceptions")
    print("=" * 60)

    eg = ExceptionGroup("batch errors", [
        ValueError("invalid input"),
        TypeError("wrong type"),
        ConnectionError("network down"),
    ])

    for i, exc in enumerate(eg.exceptions):
        print(f"  [{i}] {type(exc).__name__}: {exc}")


# ============================================================
# 3. 使用 .subgroup() 过滤特定类型
# ============================================================
def demo_subgroup():
    print("\n" + "=" * 60)
    print("3. .subgroup() 过滤特定类型")
    print("=" * 60)

    eg = ExceptionGroup("batch errors", [
        ValueError("invalid input"),
        TypeError("wrong type"),
        ConnectionError("network down"),
        ValueError("another bad value"),
    ])

    # subgroup 返回一个新的 ExceptionGroup，只包含匹配的异常
    value_errors = eg.subgroup(ValueError)
    print(f"  原始组: {len(eg.exceptions)} 个异常")
    print(f"  ValueError 子组: {value_errors}")
    if value_errors:
        for exc in value_errors.exceptions:
            print(f"    - {exc}")

    # 不匹配的类型返回 None
    key_errors = eg.subgroup(KeyError)
    print(f"  KeyError 子组: {key_errors}")


# ============================================================
# 4. 使用 .split() 分割为匹配和不匹配两组
# ============================================================
def demo_split():
    print("\n" + "=" * 60)
    print("4. .split() 分割异常组")
    print("=" * 60)

    eg = ExceptionGroup("batch errors", [
        ValueError("invalid input"),
        TypeError("wrong type"),
        ConnectionError("network down"),
        ValueError("another bad value"),
    ])

    # split 返回 (匹配组, 不匹配组)，任一可能为 None
    matched, rest = eg.split(ValueError)

    print("  匹配 ValueError 的:")
    if matched:
        for exc in matched.exceptions:
            print(f"    - {type(exc).__name__}: {exc}")

    print("  剩余的:")
    if rest:
        for exc in rest.exceptions:
            print(f"    - {type(exc).__name__}: {exc}")


# ============================================================
# 5. 嵌套 ExceptionGroup
# ============================================================
def demo_nested():
    print("\n" + "=" * 60)
    print("5. 嵌套 ExceptionGroup")
    print("=" * 60)

    # ExceptionGroup 中包含 ExceptionGroup
    inner_eg = ExceptionGroup("db errors", [
        ConnectionError("connection refused"),
        TimeoutError("query timeout"),
    ])

    outer_eg = ExceptionGroup("service errors", [
        ValueError("bad request"),
        inner_eg,  # 嵌套的 ExceptionGroup
        RuntimeError("unexpected"),
    ])

    print(f"  外层组: {outer_eg.args[0]}，包含 {len(outer_eg.exceptions)} 个条目")
    for i, exc in enumerate(outer_eg.exceptions):
        if isinstance(exc, ExceptionGroup):
            print(f"  [{i}] 嵌套组 '{exc.args[0]}'，包含 {len(exc.exceptions)} 个异常:")
            for j, inner_exc in enumerate(exc.exceptions):
                print(f"       [{i}.{j}] {type(inner_exc).__name__}: {inner_exc}")
        else:
            print(f"  [{i}] {type(exc).__name__}: {exc}")

    # subgroup 会递归搜索嵌套结构
    print("\n  subgroup(ConnectionError) 递归搜索:")
    conn_errors = outer_eg.subgroup(ConnectionError)
    if conn_errors:
        print(f"    找到: {conn_errors}")


# ============================================================
# 6. 用 traceback 展示格式化输出
# ============================================================
def demo_traceback_format():
    print("\n" + "=" * 60)
    print("6. traceback 格式化 ExceptionGroup")
    print("=" * 60)

    try:
        raise ExceptionGroup("demo errors", [
            ValueError("value problem"),
            TypeError("type problem"),
        ])
    except ExceptionGroup:
        print("  格式化输出:")
        traceback.print_exc()
    print()


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    demo_create()
    demo_iterate()
    demo_subgroup()
    demo_split()
    demo_nested()
    demo_traceback_format()
    print("=" * 60)
    print("全部演示完成")
    print("=" * 60)