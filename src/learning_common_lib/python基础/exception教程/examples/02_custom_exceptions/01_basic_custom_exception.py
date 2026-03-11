"""
目标: 演示带结构化字段的自定义异常 vs 纯字符串异常的调试体验差异
关键 API: Exception, __str__, __repr__
Python 版本: 3.11+
运行命令: uv run python examples/02_custom_exceptions/01_basic_custom_exception.py  (从 exception教程/ 目录)
预期现象: 对比纯字符串异常和结构化异常的调试输出
生产提醒: 结构化异常让你可以在 except 块中根据字段做判断，而不是解析字符串
"""


# ── 反面示例：纯字符串异常 ──

def find_user_bad(user_id: int) -> dict:
    """用纯字符串描述错误 — 调试时只能靠肉眼解析。"""
    raise ValueError(f"user {user_id} not found in database users")


# ── 正面示例：结构化自定义异常 ──

class NotFoundError(Exception):
    """资源未找到异常，携带结构化字段。"""

    def __init__(self, resource: str, resource_id: str | int, message: str = "") -> None:
        self.resource = resource
        self.resource_id = resource_id
        self.message = message or f"{resource} (id={resource_id}) 未找到"
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.resource}] id={self.resource_id}: {self.message}"

    def __repr__(self) -> str:
        return (
            f"NotFoundError(resource={self.resource!r}, "
            f"resource_id={self.resource_id!r}, "
            f"message={self.message!r})"
        )


def find_user_good(user_id: int) -> dict:
    """用结构化异常描述错误 — 调试时可以直接访问字段。"""
    raise NotFoundError(resource="User", resource_id=user_id)


# ── 对比调试体验 ──

def compare_debugging() -> None:
    """对比两种异常在 except 块中的调试体验。"""

    # 反面示例
    print("=" * 50)
    print("反面示例：纯字符串异常")
    print("=" * 50)
    try:
        find_user_bad(123)
    except ValueError as e:
        print(f"  type  : {type(e).__name__}")
        print(f"  args  : {e.args}")
        print(f"  str   : {e}")
        print("  → 想知道是哪个资源？哪个 ID？只能解析字符串...")

    # 正面示例
    print(f"\n{'='*50}")
    print("正面示例：结构化自定义异常")
    print("=" * 50)
    try:
        find_user_good(123)
    except NotFoundError as e:
        print(f"  type        : {type(e).__name__}")
        print(f"  args        : {e.args}")
        print(f"  str         : {e}")
        print(f"  repr        : {repr(e)}")
        print(f"  e.resource  : {e.resource}")
        print(f"  e.resource_id: {e.resource_id}")
        print(f"  e.message   : {e.message}")
        print("  → 字段直接可用，无需解析字符串！")

    # 结构化异常的实际用途：根据字段做判断
    print(f"\n{'='*50}")
    print("实际用途：根据字段做判断")
    print("=" * 50)
    try:
        find_user_good(456)
    except NotFoundError as e:
        if e.resource == "User":
            print(f"  用户 {e.resource_id} 不存在，可以引导注册")
        else:
            print(f"  {e.resource} {e.resource_id} 不存在，返回 404")


if __name__ == "__main__":
    compare_debugging()
