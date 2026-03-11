"""
目标: 演示异常发生时的资源清理保证
关键 API: try/finally, with, contextlib.contextmanager
Python 版本: 3.11+
运行命令: uv run python examples/05_context_manager_errors/02_cleanup_on_error.py  (从 exception教程/ 目录)
预期现象: 对比 try/finally 和 with 语句的清理行为
生产提醒: 任何获取外部资源的代码都应该用上下文管理器保证清理，不要依赖手动 try/finally
"""

from contextlib import contextmanager


# ── 模拟资源 ──
class FakeDBConnection:
    def __init__(self, name):
        self.name = name
        self.connected = False

    def connect(self):
        print(f"  [{self.name}] 连接建立")
        self.connected = True

    def close(self):
        print(f"  [{self.name}] 连接关闭")
        self.connected = False

    def execute(self, sql):
        if not self.connected:
            raise RuntimeError(f"[{self.name}] 未连接")
        if "DROP" in sql:
            raise PermissionError(f"[{self.name}] 无权执行: {sql}")
        print(f"  [{self.name}] 执行: {sql}")


# ============================================================
# 1. 手动 try/finally 清理
# ============================================================
def demo_try_finally():
    print("=" * 60)
    print("1. 手动 try/finally 清理")
    print("=" * 60)

    conn = FakeDBConnection("try-finally")
    conn.connect()
    try:
        conn.execute("SELECT * FROM users")
        conn.execute("DROP TABLE users")  # 会抛出 PermissionError
    except PermissionError as e:
        print(f"  捕获异常: {e}")
    finally:
        conn.close()  # 无论是否异常，都会执行
        print(f"  连接状态: connected={conn.connected}")


# ============================================================
# 2. 用 with 语句（__enter__/__exit__）实现同样的清理
# ============================================================
class ManagedDBConnection:
    """用上下文管理器协议包装 FakeDBConnection。"""

    def __init__(self, name):
        self._conn = FakeDBConnection(name)

    def __enter__(self):
        self._conn.connect()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._conn.close()  # 无论是否异常，都会关闭
        return False  # 不吞异常


def demo_with_statement():
    print("\n" + "=" * 60)
    print("2. with 语句自动清理")
    print("=" * 60)

    try:
        with ManagedDBConnection("with-stmt") as conn:
            conn.execute("SELECT * FROM users")
            conn.execute("DROP TABLE users")  # 抛出 PermissionError
    except PermissionError as e:
        print(f"  捕获异常: {e}")
    print("  with 语句保证了 __exit__ 被调用，连接已关闭")


# ============================================================
# 3. 用 contextlib.contextmanager 装饰器简化
# ============================================================
@contextmanager
def db_connection(name):
    """用 contextmanager 装饰器简化上下文管理器的编写。"""
    conn = FakeDBConnection(name)
    conn.connect()
    try:
        yield conn  # yield 之前是 __enter__，之后是 __exit__
    finally:
        conn.close()  # finally 保证清理


def demo_contextmanager():
    print("\n" + "=" * 60)
    print("3. contextlib.contextmanager 装饰器")
    print("=" * 60)

    try:
        with db_connection("ctx-mgr") as conn:
            conn.execute("SELECT 1")
            conn.execute("DROP TABLE orders")
    except PermissionError as e:
        print(f"  捕获异常: {e}")
    print("  contextmanager 中的 finally 保证了清理")


# ============================================================
# 4. 嵌套 with 的清理顺序：LIFO（后进先出）
# ============================================================
def demo_nested_cleanup_order():
    print("\n" + "=" * 60)
    print("4. 嵌套 with 的清理顺序 — LIFO")
    print("=" * 60)

    try:
        with db_connection("外层-A") as conn_a:
            with db_connection("中层-B") as conn_b:
                with db_connection("内层-C") as conn_c:
                    conn_a.execute("SELECT 1")
                    conn_b.execute("SELECT 2")
                    conn_c.execute("DROP TABLE secrets")  # 抛异常
    except PermissionError as e:
        print(f"  捕获异常: {e}")
    print("  清理顺序: 内层-C → 中层-B → 外层-A（LIFO）")


# ============================================================
# 5. 常见错误：__init__ 中获取资源导致泄漏
# ============================================================
class LeakyResource:
    """
    反面教材：在 __init__ 中获取资源。
    如果 __init__ 成功但 with 语句的 __enter__ 之前出错，
    或者 __init__ 中部分资源获取成功后续失败，资源会泄漏。
    """

    def __init__(self, name):
        self.name = name
        # 在 __init__ 中就获取了资源
        self.conn = FakeDBConnection(name)
        self.conn.connect()
        print(f"  [LeakyResource] {name}: __init__ 中连接已建立")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False


class SafeResource:
    """正确做法：在 __enter__ 中获取资源。"""

    def __init__(self, name):
        self.name = name
        self.conn = FakeDBConnection(name)

    def __enter__(self):
        self.conn.connect()  # 资源获取放在 __enter__ 中
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False


def demo_init_vs_enter():
    print("\n" + "=" * 60)
    print("5. __init__ vs __enter__ 获取资源")
    print("=" * 60)

    # LeakyResource: 如果在 with 之前出错，连接已建立但不会被清理
    print("\n--- 反面教材: __init__ 中获取资源 ---")
    print("  如果构造后、进入 with 前出错，资源泄漏！")
    resource = LeakyResource("leaky")
    # 假设这里出了错，resource.conn 永远不会被 close
    # （演示中我们手动关闭）
    resource.conn.close()
    print(f"  手动关闭: connected={resource.conn.connected}")

    # SafeResource: 资源在 __enter__ 中获取，with 保证 __exit__ 清理
    print("\n--- 正确做法: __enter__ 中获取资源 ---")
    with SafeResource("safe") as res:
        res.conn.execute("SELECT 1")
    print(f"  with 退出后: connected={res.conn.connected}")


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    demo_try_finally()
    demo_with_statement()
    demo_contextmanager()
    demo_nested_cleanup_order()
    demo_init_vs_enter()
    print("\n" + "=" * 60)
    print("全部演示完成")
    print("=" * 60)