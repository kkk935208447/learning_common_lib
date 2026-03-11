"""
目标: 直接对比反模式（字符串拼接 re-raise）和正确做法（raise from）在深层调用栈下的效果
关键 API: raise from, traceback
Python 版本: 3.11+
运行命令: uv run python examples/03_exception_chain/02_anti_pattern_vs_correct.py  (从 exception教程/ 目录)
预期现象: 反模式丢失原始 traceback，正确做法保留完整链路
生产提醒: 字符串拼接 re-raise 是异常处理中最常见的反模式，它把结构化的异常链变成了一个扁平字符串
"""

import traceback


# ── 自定义异常（正确版本使用）──

class ServiceError(Exception):
    """服务层异常。"""
    pass


# ══════════════════════════════════════════════════════════
#  反模式版本：每层都 catch + 字符串拼接 re-raise
# ══════════════════════════════════════════════════════════

def bad_database_query(query: str) -> dict:
    """第 1 层：数据库查询。"""
    raise ConnectionError(f"无法连接到数据库: timeout after 5s")


def bad_repository_get(user_id: int) -> dict:
    """第 2 层：仓储层。"""
    try:
        return bad_database_query(f"SELECT * FROM users WHERE id={user_id}")
    except Exception as e:
        raise RuntimeError(f"repository_get 失败: {e}")


def bad_service_find(user_id: int) -> dict:
    """第 3 层：服务层。"""
    try:
        return bad_repository_get(user_id)
    except Exception as e:
        raise RuntimeError(f"service_find 失败: {e}")


def bad_controller_handle(request: dict) -> dict:
    """第 4 层：控制器层。"""
    try:
        return bad_service_find(request["user_id"])
    except Exception as e:
        raise RuntimeError(f"controller_handle 失败: {e}")


# ══════════════════════════════════════════════════════════
#  正确版本：只在边界层转换异常，其他层让异常自然传播
# ══════════════════════════════════════════════════════════

def good_database_query(query: str) -> dict:
    """第 1 层：数据库查询（原始异常）。"""
    raise ConnectionError(f"无法连接到数据库: timeout after 5s")


class RepositoryError(Exception):
    """仓储层异常。"""
    pass


def good_repository_get(user_id: int) -> dict:
    """第 2 层：仓储层 — 边界转换，捕获底层异常并用 raise from 包装。"""
    try:
        return good_database_query(f"SELECT * FROM users WHERE id={user_id}")
    except ConnectionError as e:
        raise RepositoryError(f"查询用户 {user_id} 失败") from e


def good_service_find(user_id: int) -> dict:
    """第 3 层：服务层 — 透传仓储层异常，业务逻辑判断时才 raise ServiceError。"""
    try:
        return good_repository_get(user_id)
    except RepositoryError as e:
        raise ServiceError(f"查找用户 {user_id} 失败") from e


def good_controller_handle(request: dict) -> dict:
    """第 4 层：控制器层 — 不捕获 ServiceError，让框架处理。"""
    return good_service_find(request["user_id"])


# ── 运行对比 ──

def run_and_show(label: str, func: callable, *args) -> None:
    """运行函数并打印 traceback。"""
    print(f"\n{'='*65}")
    print(f"  {label}")
    print("=" * 65)
    try:
        func(*args)
    except Exception as e:
        tb_text = traceback.format_exception(type(e), e, e.__traceback__)
        print("".join(tb_text))
        # 检查异常链是否保留
        print(f"  最终异常类型: {type(e).__name__}")
        print(f"  最终异常消息: {e}")
        print(f"  __cause__   : {e.__cause__!r}")
        print(f"  __context__ : {e.__context__!r}")


if __name__ == "__main__":
    request = {"user_id": 42}

    run_and_show(
        "反模式：字符串拼接 re-raise（原始异常信息被压扁成字符串）",
        bad_controller_handle,
        request,
    )

    run_and_show(
        "正确做法：raise from + 让异常自然传播（完整链路保留）",
        good_controller_handle,
        request,
    )

    print(f"\n{'='*65}")
    print("对比总结")
    print("=" * 65)
    print("  反模式: 每层 catch + 字符串拼接")
    print("    → 最终只看到 'controller_handle 失败: service_find 失败: ...'")
    print("    → 原始 ConnectionError 的 traceback 完全丢失")
    print("    → __cause__ 和 __context__ 都是 None")
    print()
    print("  正确做法: 仓储层边界转换 + 服务层转换 + 控制器不捕获")
    print("    → 仓储层: ConnectionError → RepositoryError (边界转换)")
    print("    → 服务层: RepositoryError → ServiceError (业务转换)")
    print("    → __cause__ 链完整: ServiceError → RepositoryError → ConnectionError")
    print("    → 调试时可以直接定位到真正出错的那一行")
