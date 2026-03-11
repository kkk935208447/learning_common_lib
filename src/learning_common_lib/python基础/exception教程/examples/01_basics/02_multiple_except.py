"""
目标: 演示多异常捕获的匹配顺序和写法
关键 API: except, except (T1, T2), except Exception, except BaseException
Python 版本: 3.11+
运行命令: uv run python examples/01_basics/02_multiple_except.py  (从 exception教程/ 目录)
预期现象: 展示匹配顺序、合并写法、Exception vs BaseException 的区别
生产提醒: 永远不要用 except BaseException，除非你在写框架级别的顶层错误处理
"""


# ── 第一部分：自定义异常层级，演示子类优先匹配 ──

class AppError(Exception):
    """应用基础异常。"""
    pass


class DatabaseError(AppError):
    """数据库异常（AppError 的子类）。"""
    pass


class ConnectionError_(DatabaseError):
    """连接异常（DatabaseError 的子类）。"""
    pass


def demo_match_order() -> None:
    """多个 except 分支按从上到下匹配，子类必须放在父类前面。"""
    print("=" * 50)
    print("第一部分：匹配顺序 — 子类优先")
    print("=" * 50)

    for exc_class in [ConnectionError_, DatabaseError, AppError]:
        try:
            raise exc_class(f"模拟 {exc_class.__name__}")
        except ConnectionError_ as e:
            print(f"  [ConnectionError_] 捕获: {e}")
        except DatabaseError as e:
            print(f"  [DatabaseError]    捕获: {e}")
        except AppError as e:
            print(f"  [AppError]         捕获: {e}")

    # 反面示例：如果把父类放前面，子类永远匹配不到
    print("\n  ⚠ 如果把 AppError 放最前面：")
    try:
        raise ConnectionError_("连接超时")
    except AppError as e:
        print(f"  [AppError] 捕获了本应由 ConnectionError_ 处理的异常: {e}")
        print("  → 子类 except 分支被跳过了！")
    except ConnectionError_ as e:
        print(f"  [ConnectionError_] 跳过: {e}")


# ── 第二部分：合并写法 ──

def demo_tuple_except() -> None:
    """用元组合并多个异常类型到同一个 except 分支。"""
    print(f"\n{'='*50}")
    print("第二部分：合并写法 except (T1, T2)")
    print("=" * 50)

    test_cases = [
        TypeError("类型错误"),
        ValueError("值错误"),
        KeyError("键错误"),
    ]
    for exc in test_cases:
        try:
            raise exc
        except (TypeError, ValueError) as e:
            print(f"  [TypeError|ValueError] 捕获: {type(e).__name__}: {e}")
        except Exception as e:
            print(f"  [Exception]            捕获: {type(e).__name__}: {e}")


# ── 第三部分：Exception vs BaseException ──

def demo_exception_vs_base() -> None:
    """展示 Exception 和 BaseException 的继承关系差异。"""
    print(f"\n{'='*50}")
    print("第三部分：Exception vs BaseException")
    print("=" * 50)

    # 展示继承关系
    print("\n  继承关系:")
    print("  BaseException")
    print("  ├── SystemExit")
    print("  ├── KeyboardInterrupt")
    print("  ├── GeneratorExit")
    print("  └── Exception")
    print("      ├── ValueError")
    print("      ├── TypeError")
    print("      └── ...")

    # except Exception 不会捕获 SystemExit / KeyboardInterrupt
    print("\n  测试 except Exception:")
    for exc in [ValueError("普通异常"), SystemExit(1), KeyboardInterrupt()]:
        try:
            raise exc
        except Exception as e:
            print(f"    [Exception] 捕获到: {type(e).__name__}")
        except BaseException as e:
            print(f"    [BaseException] 捕获到: {type(e).__name__} — except Exception 漏掉了它！")

    print("\n  结论: except Exception 不会拦截 SystemExit 和 KeyboardInterrupt")
    print("  这是正确的行为 — 你不应该阻止程序退出或中断信号")


if __name__ == "__main__":
    demo_match_order()
    demo_tuple_except()
    demo_exception_vs_base()
