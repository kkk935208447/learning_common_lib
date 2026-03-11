"""
目标: 演示 contextlib.suppress 和 __exit__ 返回值对异常传播的影响
关键 API: contextlib.suppress, __enter__, __exit__
Python 版本: 3.11+
运行命令: uv run python examples/05_context_manager_errors/01_suppress_and_handle.py  (从 exception教程/ 目录)
预期现象: 展示 suppress 吞异常、__exit__ 返回 True/False 的区别
生产提醒: __exit__ 返回 True 会吞掉异常，这是一个容易被忽略的行为，务必明确意图
"""

import contextlib
import logging

# ── 配置日志 ──
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 1. contextlib.suppress — 抑制指定异常，其他异常照常传播
# ============================================================
def demo_suppress():
    print("=" * 60)
    print("1. contextlib.suppress 演示")
    print("=" * 60)

    # FileNotFoundError 被抑制，不会抛出
    print("\n--- 抑制 FileNotFoundError ---")
    with contextlib.suppress(FileNotFoundError):
        open("/tmp/不存在的文件_abc123.txt")  # noqa: SIM115
    print("  FileNotFoundError 被抑制，程序继续执行")

    # TypeError 不在 suppress 列表中，会正常抛出
    print("\n--- TypeError 不被抑制 ---")
    try:
        with contextlib.suppress(FileNotFoundError):
            raise TypeError("这个异常不会被抑制")
    except TypeError as e:
        print(f"  TypeError 正常传播: {e}")


# ============================================================
# 2. 自定义上下文管理器，__exit__ 返回 True — 吞掉异常
# ============================================================
class SwallowAll:
    """__exit__ 返回 True，吞掉所有异常。"""

    def __enter__(self):
        print("  SwallowAll: 进入上下文")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            print(f"  SwallowAll: 捕获到 {exc_type.__name__}: {exc_val}")
        print("  SwallowAll: __exit__ 返回 True，异常被吞掉")
        return True  # 吞掉所有异常


def demo_swallow_all():
    print("\n" + "=" * 60)
    print("2. __exit__ 返回 True — 吞掉异常")
    print("=" * 60)

    with SwallowAll():
        raise ValueError("这个异常会被吞掉")
    print("  ValueError 被吞掉，程序继续执行")


# ============================================================
# 3. 自定义上下文管理器，__exit__ 返回 False/None — 异常继续传播
# ============================================================
class LetItGo:
    """__exit__ 返回 False，异常继续传播。"""

    def __enter__(self):
        print("  LetItGo: 进入上下文")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            print(f"  LetItGo: 看到 {exc_type.__name__}: {exc_val}")
        print("  LetItGo: __exit__ 返回 False，异常继续传播")
        return False  # 不吞异常


def demo_let_it_go():
    print("\n" + "=" * 60)
    print("3. __exit__ 返回 False/None — 异常继续传播")
    print("=" * 60)

    try:
        with LetItGo():
            raise ValueError("这个异常会继续传播")
    except ValueError as e:
        print(f"  外层捕获到 ValueError: {e}")


# ============================================================
# 4. 实际场景：ErrorBoundary 上下文管理器
# ============================================================
class ErrorBoundary:
    """只吞指定类型的异常，其他异常继续传播。"""

    def __init__(self, *catch_types, logger=None):
        self.catch_types = catch_types
        self.logger = logger

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and issubclass(exc_type, self.catch_types):
            if self.logger:
                self.logger.warning("suppressed: %s", exc_val)
            return True  # 吞掉
        return False  # 传播


def demo_error_boundary():
    print("\n" + "=" * 60)
    print("4. ErrorBoundary — 只吞特定类型的异常")
    print("=" * 60)

    # 4a: ValueError 被 ErrorBoundary 吞掉并记录日志
    print("\n--- 4a: ValueError 被吞掉 ---")
    with ErrorBoundary(ValueError, TypeError, logger=logger):
        raise ValueError("无效的输入值")
    print("  ValueError 被 ErrorBoundary 吞掉，程序继续")

    # 4b: RuntimeError 不在捕获列表中，继续传播
    print("\n--- 4b: RuntimeError 继续传播 ---")
    try:
        with ErrorBoundary(ValueError, TypeError, logger=logger):
            raise RuntimeError("运行时错误")
    except RuntimeError as e:
        print(f"  RuntimeError 传播到外层: {e}")

    # 4c: 不带 logger 的 ErrorBoundary
    print("\n--- 4c: 不带 logger，静默吞掉 ---")
    with ErrorBoundary(KeyError):
        raise KeyError("missing_key")
    print("  KeyError 被静默吞掉")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    demo_suppress()
    demo_swallow_all()
    demo_let_it_go()
    demo_error_boundary()
    print("\n" + "=" * 60)
    print("全部演示完成")
    print("=" * 60)