"""
目标: 演示 try/except/else/finally 四个分支的执行顺序
关键 API: try, except, else, finally
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/01_try_except_else_finally.py  (从 exception教程/ 目录)
预期现象: 三种场景（无异常、捕获异常、未捕获异常）各打印执行流
生产提醒: else 块适合放"只在成功时执行"的逻辑，比如提交事务；finally 块只做清理
"""


def divide(a: float, b: float) -> float:
    """除法运算，用于演示异常分支。"""
    return a / b


def demo_scenario(name: str, a: float, b: float) -> None:
    """运行一个场景，打印每个分支的执行情况。"""
    print(f"\n{'='*50}")
    print(f"{name}")
    print(f"{'='*50}")
    try:
        print("  [try] 开始执行除法...")
        result = divide(a, b)
        print(f"  [try] 除法成功，结果 = {result}")
    except ZeroDivisionError as e:
        print(f"  [except] 捕获到 ZeroDivisionError: {e}")
    else:
        # 只在 try 块没有异常时执行
        print(f"  [else] 没有异常，可以安全使用 result = {result}")
    finally:
        # 无论如何都会执行
        print("  [finally] 清理资源（无论是否异常都会执行）")


def demo_uncaught() -> None:
    """场景三：未捕获异常 — try → finally → 异常传播。"""
    print(f"\n{'='*50}")
    print("场景三：未捕获异常 — try → finally → 异常传播")
    print(f"{'='*50}")
    try:
        print("  [try] 开始执行除法...")
        result = divide(1, 0)
        print(f"  [try] 这行不会执行，结果 = {result}")
    except TypeError as e:
        # 故意只捕获 TypeError，让 ZeroDivisionError 逃逸
        print(f"  [except TypeError] 捕获到: {e}")
    finally:
        print("  [finally] 即使异常未被捕获，finally 仍然执行！")
    # ZeroDivisionError 会在 finally 之后传播出去


if __name__ == "__main__":
    # 场景一：无异常 — try → else → finally
    demo_scenario("场景一：无异常 — try → else → finally", 10, 3)

    # 场景二：捕获异常 — try → except → finally
    demo_scenario("场景二：捕获异常 — try → except → finally", 10, 0)

    # 场景三：未捕获异常 — try → finally → 异常传播
    try:
        demo_uncaught()
    except ZeroDivisionError as e:
        print(f"  [外层捕获] ZeroDivisionError 传播到了外层: {e}")

    print(f"\n{'='*50}")
    print("总结：执行顺序")
    print(f"{'='*50}")
    print("  无异常:   try → else → finally")
    print("  捕获异常: try → except → finally")
    print("  未捕获:   try → finally → 异常向上传播")
