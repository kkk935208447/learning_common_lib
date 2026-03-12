"""
目标: 用 dataclass 实现 Result[T] 类型，演示不用异常的错误传递方式
关键 API: dataclass, Generic, TypeVar
Python 版本: 3.11+
运行命令: uv run python examples/07_deep_call_stack/02_result_pattern.py  (从 exception教程/ 目录)
预期现象: 展示 Result 模式的用法和与异常方式的对比
生产提醒: Result 模式适合预期内的业务错误（如验证失败），异常适合意外的系统错误（如数据库宕机）；两者可以混用
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, Generic

T = TypeVar("T")


# ============================================================
# UnwrapError — unwrap 失败时的专用异常
# ============================================================
# 设计取舍：用自定义异常而非 ValueError，原因：
#   1. 调用方可以精确 except UnwrapError，不会误捕其他 ValueError
#   2. 携带 error_code 字段，方便上层按错误码分流处理
#   3. 与 Rust 的 unwrap panic 语义对齐——这是编程错误，不是业务错误

class UnwrapError(Exception):
    """对错误 Result 调用 unwrap() 时抛出。"""

    def __init__(self, error: str, error_code: str) -> None:
        self.error = error
        self.error_code = error_code
        super().__init__(f"[{error_code}] {error}")


# ============================================================
# Result[T] 类型定义
# ============================================================

@dataclass(frozen=True, slots=True)  #  frozen=True 确保不可变性，slots=True 优化内存布局
class Result(Generic[T]):
    """函数式错误处理：用返回值代替异常。"""
    value: T | None = None
    error: str | None = None
    error_code: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_err(self) -> bool:
        return self.error is not None

    @staticmethod
    def ok(value: T) -> Result[T]:
        return Result(value=value)

    @staticmethod
    def err(error: str, code: str = "UNKNOWN") -> Result[T]:
        return Result(error=error, error_code=code)

    def unwrap(self) -> T:
        """获取值，如果是错误则抛出 UnwrapError。"""
        if self.is_err:
            raise UnwrapError(self.error, self.error_code)  # type: ignore[arg-type]
        return self.value  # type: ignore


# ============================================================
# Result 模式：3 层调用栈
# ============================================================

def parse_user_id(raw: str) -> Result[int]:
    """解析用户 ID，返回 Result。"""
    try:
        return Result.ok(int(raw))
    except ValueError:
        return Result.err(f"无法解析用户 ID: {raw!r}", "INVALID_ID")


def find_user(user_id: int) -> Result[dict]:
    """查找用户，返回 Result。"""
    users = {1: {"name": "Alice"}, 2: {"name": "Bob"}}
    user = users.get(user_id)
    if user is None:
        return Result.err(f"用户 {user_id} 不存在", "USER_NOT_FOUND")
    return Result.ok(user)


def process_request(raw_id: str) -> Result[str]:
    """处理请求：解析 ID → 查找用户 → 返回问候语。"""
    id_result = parse_user_id(raw_id)
    if id_result.is_err:
        return id_result  # type: ignore  # 透传错误

    user_result = find_user(id_result.unwrap())
    if user_result.is_err:
        return user_result  # type: ignore  # 透传错误

    return Result.ok(f"Hello, {user_result.unwrap()['name']}!")


# ============================================================
# 异常模式：同样的逻辑，用异常实现
# ============================================================

class InvalidIdError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


def parse_user_id_exc(raw: str) -> int:
    """解析用户 ID，失败抛异常。"""
    try:
        return int(raw)
    except ValueError:
        raise InvalidIdError(f"无法解析用户 ID: {raw!r}")


def find_user_exc(user_id: int) -> dict:
    """查找用户，失败抛异常。"""
    users = {1: {"name": "Alice"}, 2: {"name": "Bob"}}
    user = users.get(user_id)
    if user is None:
        raise UserNotFoundError(f"用户 {user_id} 不存在")
    return user


def process_request_exc(raw_id: str) -> str:
    """处理请求：异常版本——不需要手动检查错误。"""
    user_id = parse_user_id_exc(raw_id)
    user = find_user_exc(user_id)
    return f"Hello, {user['name']}!"


# ============================================================
# 演示运行
# ============================================================

if __name__ == "__main__":
    # --- Result 模式演示 ---
    print("=" * 60)
    print("Result 模式演示")
    print("=" * 60)

    test_cases = ["1", "2", "abc", "99"]
    for raw_id in test_cases:
        result = process_request(raw_id)
        if result.is_ok:
            print(f"  输入 {raw_id!r:>5} → OK: {result.unwrap()}")
        else:
            print(f"  输入 {raw_id!r:>5} → ERR [{result.error_code}]: {result.error}")

    # --- 异常模式演示 ---
    print(f"\n{'=' * 60}")
    print("异常模式演示（同样的逻辑）")
    print("=" * 60)

    for raw_id in test_cases:
        try:
            greeting = process_request_exc(raw_id)
            print(f"  输入 {raw_id!r:>5} → OK: {greeting}")
        except (InvalidIdError, UserNotFoundError) as e:
            print(f"  输入 {raw_id!r:>5} → ERR: {e}")

    # --- unwrap 演示 ---
    print(f"\n{'=' * 60}")
    print("unwrap() 演示：对错误结果调用 unwrap 会抛出异常")
    print("=" * 60)

    err_result = Result.err("测试错误", "TEST_ERR")
    try:
        err_result.unwrap()
    except UnwrapError as e:
        print(f"  捕获到 UnwrapError: {e}")
        print(f"  error_code={e.error_code}, error={e.error}")

    # --- 对比表 ---
    print(f"\n{'=' * 60}")
    print("=== Result 模式 vs 异常模式对比 ===")
    print("=" * 60)
    print("""
| 维度         | Result 模式          | 异常模式              |
|-------------|---------------------|----------------------|
| 错误可见性    | 函数签名中可见         | 隐式，需要看文档       |
| 性能         | 无异常开销            | 异常有栈展开开销       |
| 强制处理     | 编译器不强制（Python） | 不强制                |
| 适用场景     | 预期内的业务错误       | 意外的系统错误         |
| 代码风格     | 函数式               | 命令式                |

混用建议:
  - 验证失败、资源不存在等「预期内」错误 → Result 模式
  - 数据库宕机、网络超时等「意外」错误 → 异常模式
  - 两者可以在同一项目中共存，按场景选择
""")
