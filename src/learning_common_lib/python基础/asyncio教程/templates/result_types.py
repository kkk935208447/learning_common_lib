"""
解决什么问题: 统一异步任务的结果表示，避免全项目传裸 dict
输入输出约定: 每个结果包含 name, ok, result/error, status(ok/error/timeout/cancelled)
失败策略: 不涉及，纯数据结构
取消语义: 不涉及
不适用场景: 不需要结构化结果的简单脚本
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class TaskResult:
    """统一的异步任务结果。"""

    name: str
    ok: bool
    result: Any | None
    error: str | None
    error_type: str | None
    status: Literal["ok", "error", "timeout", "cancelled"]

    # ---- factory classmethods ------------------------------------------------

    @classmethod
    def success(cls, name: str, result: Any) -> TaskResult:
        return cls(name=name, ok=True, result=result, error=None, error_type=None, status="ok")

    @classmethod
    def from_error(cls, name: str, exc: BaseException) -> TaskResult:
        return cls(
            name=name,
            ok=False,
            result=None,
            error=str(exc),
            error_type=type(exc).__qualname__,
            status="error",
        )

    @classmethod
    def from_timeout(cls, name: str) -> TaskResult:
        return cls(name=name, ok=False, result=None, error="timeout", error_type="TimeoutError", status="timeout")

    @classmethod
    def from_cancelled(cls, name: str) -> TaskResult:
        return cls(
            name=name, ok=False, result=None, error="cancelled", error_type="CancelledError", status="cancelled"
        )


if __name__ == "__main__":
    r1 = TaskResult.success("demo-ok", {"value": 42})
    r2 = TaskResult.from_error("demo-err", RuntimeError("something broke"))
    r3 = TaskResult.from_timeout("demo-timeout")
    r4 = TaskResult.from_cancelled("demo-cancel")

    for r in (r1, r2, r3, r4):
        print(f"{r.name}: status={r.status}, ok={r.ok}, error_type={r.error_type}, result={r.result}, error={r.error}")
