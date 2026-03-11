"""
目标: 演示 traceback 模块的格式化功能
关键 API: traceback.format_exc, traceback.format_exception, traceback.extract_tb
Python 版本: 3.11+
运行命令: uv run python examples/04_traceback_logging/01_traceback_format.py  (从 exception教程/ 目录)
预期现象: 展示不同格式化方法的输出
生产提醒: 生产环境中用 logging.exception() 比手动 traceback 更方便，但 traceback 模块在需要自定义格式时很有用
"""

import sys
import traceback


# ── 构造一个 3 层调用栈 ──

def layer_3_database(query: str) -> dict:
    """第 3 层：模拟数据库查询失败。"""
    raise ConnectionError(f"连接超时: {query}")


def layer_2_repository(user_id: int) -> dict:
    """第 2 层：仓储层调用数据库。"""
    return layer_3_database(f"SELECT * FROM users WHERE id={user_id}")


def layer_1_service(user_id: int) -> dict:
    """第 1 层：服务层调用仓储。"""
    return layer_2_repository(user_id)


# ── 方法一：traceback.format_exc() ──

def demo_format_exc() -> None:
    """在 except 块中获取当前异常的格式化字符串。"""
    print("=" * 60)
    print("方法一：traceback.format_exc()")
    print("  用途：在 except 块中获取当前异常的完整 traceback 字符串")
    print("=" * 60)
    try:
        layer_1_service(42)
    except ConnectionError:
        tb_str = traceback.format_exc()
        print(tb_str)


# ── 方法二：traceback.format_exception(type, value, tb) ──

def demo_format_exception() -> None:
    """格式化指定的异常对象（不依赖 except 块上下文）。"""
    print("=" * 60)
    print("方法二：traceback.format_exception(type, value, tb)")
    print("  用途：格式化任意异常对象，不需要在 except 块中")
    print("=" * 60)
    try:
        layer_1_service(42)
    except ConnectionError as e:
        # 保存异常信息
        exc_type, exc_value, exc_tb = sys.exc_info()
        # 也可以直接用异常对象
        lines = traceback.format_exception(type(e), e, e.__traceback__)
        print("".join(lines))


# ── 方法三：traceback.extract_tb(tb) ──

def demo_extract_tb() -> None:
    """提取帧信息，遍历每一帧打印文件名、行号、函数名。"""
    print("=" * 60)
    print("方法三：traceback.extract_tb(tb)")
    print("  用途：提取结构化的帧信息，可以自定义格式")
    print("=" * 60)
    try:
        layer_1_service(42)
    except ConnectionError as e:
        frames = traceback.extract_tb(e.__traceback__)
        print(f"\n  共 {len(frames)} 帧:\n")
        for i, frame in enumerate(frames):
            print(f"  帧 {i}:")
            print(f"    文件: {frame.filename}")
            print(f"    行号: {frame.lineno}")
            print(f"    函数: {frame.name}")
            print(f"    代码: {frame.line}")
            print()


# ── 方法四：limit 参数 — 只获取最后 N 帧 ──

def demo_limit() -> None:
    """用 limit 参数控制 traceback 深度。"""
    print("=" * 60)
    print("方法四：limit 参数 — 只获取最后 N 帧")
    print("  用途：调用栈很深时，只关注最近的几帧")
    print("=" * 60)
    try:
        layer_1_service(42)
    except ConnectionError:
        print("\n  limit=1（只看最内层）:")
        print(traceback.format_exc(limit=1))

        print("  limit=-1（只看最外层）:")
        print(traceback.format_exc(limit=-1))


if __name__ == "__main__":
    demo_format_exc()
    demo_format_exception()
    demo_extract_tb()
    demo_limit()
