"""
目标: 演示如何测试异常——捕获断言、结构化字段断言、__cause__ 链断言、mock 触发异常路径
关键 API: contextmanager（模拟 pytest.raises）、unittest.mock.patch
Python 版本: 3.11+
运行命令: uv run python examples/09_testing/01_pytest_exception.py  (从 exception教程/ 目录)
预期现象: 所有断言通过，展示 4 种异常测试技巧
生产提醒: 生产项目建议用 pytest + pytest.raises；本示例用标准库模拟，保持零依赖
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Type
from unittest.mock import patch


# ============================================================
# 零依赖版 raises — 模拟 pytest.raises 的核心行为
# ============================================================

@dataclass
class ExceptionInfo:
    """捕获到的异常信息，类似 pytest.ExceptionInfo。"""
    value: Exception

    @property
    def type(self) -> Type[Exception]:
        return type(self.value)


@contextmanager
def raises(expected: Type[Exception]):
    """模拟 pytest.raises：块内必须抛出指定异常，否则 AssertionError。

    用法::

        with raises(ValueError) as exc_info:
            int("abc")
        assert "invalid literal" in str(exc_info.value)
    """
    info = ExceptionInfo(value=Exception())  # placeholder
    try:
        yield info
    except expected as e:
        info.value = e
        return  # 异常被捕获，测试通过
    except Exception as e:
        raise AssertionError(
            f"期望 {expected.__name__}，实际抛出 {type(e).__name__}: {e}"
        ) from e
    else:
        raise AssertionError(f"期望 {expected.__name__}，但没有异常抛出")

# ============================================================
# 被测代码：简单的用户服务
# ============================================================

class UserNotFoundError(Exception):
    """用户不存在。"""
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"用户 {user_id} 不存在")


class DatabaseError(Exception):
    """数据库错误。"""
    pass


def get_user(user_id: int) -> dict:
    """从「数据库」获取用户。"""
    if user_id <= 0:
        raise ValueError(f"无效的用户 ID: {user_id}")
    # 模拟数据库
    users = {1: {"name": "Alice"}, 2: {"name": "Bob"}}
    user = users.get(user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


def fetch_user_from_remote(user_id: int) -> dict:
    """从远程服务获取用户（会调用外部 API）。"""
    # 实际会调用 requests.get(...)，这里用 _call_remote 模拟
    return _call_remote(user_id)


def _call_remote(user_id: int) -> dict:
    """模拟远程调用——生产中这里是 HTTP 请求。"""
    raise ConnectionError("远程服务不可用")



# ============================================================
# 测试技巧 1：基本异常捕获断言
# ============================================================

def test_basic_exception_catch() -> None:
    """验证函数抛出了预期的异常类型。"""
    print("=" * 60)
    print("测试 1：基本异常捕获断言 — raises(ValueError)")
    print("=" * 60)

    with raises(ValueError) as exc_info:
        get_user(-1)

    assert "无效的用户 ID" in str(exc_info.value)
    print(f"  PASS: 捕获到 ValueError: {exc_info.value}")


# ============================================================
# 测试技巧 2：结构化字段断言
# ============================================================

def test_structured_fields() -> None:
    """验证自定义异常的结构化字段。"""
    print(f"\n{'=' * 60}")
    print("测试 2：结构化字段断言 — 检查 user_id 字段")
    print("=" * 60)

    with raises(UserNotFoundError) as exc_info:
        get_user(999)

    err = exc_info.value
    assert isinstance(err, UserNotFoundError)
    assert err.user_id == 999
    print(f"  PASS: user_id={err.user_id}, message={err}")


# ============================================================
# 测试技巧 3：__cause__ 链断言
# ============================================================

def test_exception_chain() -> None:
    """验证 raise from 保留了异常链。"""
    print(f"\n{'=' * 60}")
    print("测试 3：__cause__ 链断言 — 验证 raise from 链路")
    print("=" * 60)

    def service_call() -> dict:
        try:
            return fetch_user_from_remote(1)
        except ConnectionError as e:
            raise DatabaseError("远程服务调用失败") from e

    with raises(DatabaseError) as exc_info:
        service_call()

    err = exc_info.value
    assert err.__cause__ is not None
    assert isinstance(err.__cause__, ConnectionError)
    print(f"  PASS: DatabaseError.__cause__ = {err.__cause__!r}")



# ============================================================
# 测试技巧 4：mock 外部依赖触发异常路径
# ============================================================

def test_mock_external_dependency() -> None:
    """用 mock.patch 模拟外部依赖失败，测试异常处理路径。"""
    print(f"\n{'=' * 60}")
    print("测试 4：mock 外部依赖 — patch _call_remote 触发异常路径")
    print("=" * 60)

    # patch _call_remote 让它抛出 ConnectionError
    with patch(f"{__name__}._call_remote", side_effect=ConnectionError("模拟网络故障")):
        with raises(ConnectionError) as exc_info:
            fetch_user_from_remote(1)

    assert "模拟网络故障" in str(exc_info.value)
    print(f"  PASS: mock 触发 ConnectionError: {exc_info.value}")

    # patch _call_remote 让它正常返回
    with patch(f"{__name__}._call_remote", return_value={"name": "MockUser"}):
        result = fetch_user_from_remote(1)
        assert result == {"name": "MockUser"}
        print(f"  PASS: mock 正常返回: {result}")


# ============================================================
# 运行所有测试
# ============================================================

if __name__ == "__main__":
    test_basic_exception_catch()
    test_structured_fields()
    test_exception_chain()
    test_mock_external_dependency()

    print(f"\n{'=' * 60}")
    print("异常测试要点")
    print("=" * 60)
    print("""
  1. raises(ExcType) 断言函数抛出了预期异常（生产用 pytest.raises）
  2. 捕获后检查结构化字段（user_id, error_code 等），不只检查消息字符串
  3. 验证 __cause__ 链完整——确保 raise from 没有被遗漏
  4. 用 mock.patch 模拟外部依赖失败，覆盖异常处理路径
  5. 生产项目建议:
     - 用 pytest + pytest.raises 替代本示例的 raises
     - 异常路径的测试覆盖率和正常路径同等重要
""")
