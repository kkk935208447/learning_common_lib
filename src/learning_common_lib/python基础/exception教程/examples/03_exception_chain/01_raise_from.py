"""
目标: 对比 raise from e（显式链）、隐式链、raise from None（抑制链）的 traceback 输出
关键 API: raise from, __cause__, __context__, __suppress_context__
Python 版本: 3.11+
运行命令: uv run python examples/03_exception_chain/01_raise_from.py  (从 exception教程/ 目录)
预期现象: 三种场景的 traceback 输出差异清晰可见
生产提醒: 99% 的场景应该用 raise from e，只有在你确定原始异常对调用者无意义时才用 from None
"""

import traceback


# ── 场景一：显式链 raise from e ──

def explicit_chain() -> None:
    """raise from e — 显式标记因果关系。"""
    try:
        int("abc")
    except ValueError as e:
        raise RuntimeError("转换失败") from e


# ── 场景二：隐式链（except 块中直接 raise 新异常）──

def implicit_chain() -> None:
    """except 块中 raise 新异常 — Python 自动记录上下文。"""
    try:
        int("abc")
    except ValueError:
        raise RuntimeError("转换失败")


# ── 场景三：抑制链 raise from None ──

def suppress_chain() -> None:
    """raise from None — 故意隐藏原始异常。"""
    try:
        int("abc")
    except ValueError:
        raise RuntimeError("转换失败") from None


# ── 工具函数：安全运行并打印 traceback ──

def run_and_show(label: str, func: callable) -> None:
    """运行函数，捕获异常并打印格式化的 traceback。"""
    print(f"\n{'='*60}")
    print(f"{label}")
    print("=" * 60)
    try:
        func()
    except RuntimeError as e:
        # 打印完整 traceback
        print("\n--- traceback 输出 ---")
        tb_text = traceback.format_exception(type(e), e, e.__traceback__)
        print("".join(tb_text))

        # 检查链属性
        print("--- 异常链属性 ---")
        print(f"  __cause__           : {e.__cause__!r}")
        print(f"  __context__         : {e.__context__!r}")
        print(f"  __suppress_context__: {e.__suppress_context__}")


if __name__ == "__main__":
    run_and_show("场景一：显式链 — raise RuntimeError('转换失败') from e", explicit_chain)
    run_and_show("场景二：隐式链 — raise RuntimeError('转换失败')（在 except 块中）", implicit_chain)
    run_and_show("场景三：抑制链 — raise RuntimeError('转换失败') from None", suppress_chain)

    print(f"\n{'='*60}")
    print("总结")
    print("=" * 60)
    print("  显式链 (from e)   : __cause__=原始异常, __suppress_context__=True")
    print("                      traceback 显示 'direct cause'")
    print("  隐式链             : __context__=原始异常, __suppress_context__=False")
    print("                      traceback 显示 'During handling'")
    print("  抑制链 (from None) : __cause__=None, __suppress_context__=True")
    print("                      traceback 不显示原始异常")
