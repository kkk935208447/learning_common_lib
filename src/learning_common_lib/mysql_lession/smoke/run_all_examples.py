"""
SQLAlchemy 异步 ORM 教程 smoke 测试

自动发现并运行 examples/ 和 templates/ 下所有示例文件，验证模块自洽。
只依赖本模块，不依赖项目其他部分。

前置条件：
    1. MySQL 服务已启动（localhost:3306, root/123456）
    2. tutorial_db 数据库已创建
    3. asyncmy 已安装（uv sync）

运行方式（从 mysql_lession/ 目录）：
    uv run python smoke/run_all_examples.py
"""

import subprocess
import sys
import time
from pathlib import Path

SKIP_FILES = {
    "__init__.py",
}

# FastAPI 示例需要启动/关闭服务器，给更多时间
TIMEOUT_SECONDS = 60


def find_py_files(base: Path) -> list[Path]:
    """递归查找 examples/ 和 templates/ 下所有 .py 文件，按路径排序。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        d = base / subdir
        if d.exists():
            files.extend(d.rglob("*.py"))
    return sorted(files)


def run_one(path: Path, base: Path) -> tuple[str, bool, str]:
    """运行单个示例，返回 (文件名, 是否成功, 输出/错误信息)。"""
    rel = path.name
    if rel in SKIP_FILES:
        return (str(path), True, "SKIPPED")

    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=str(base),  # 从 mysql_lession/ 目录运行
        )
        if result.returncode == 0:
            return (str(path), True, result.stdout[-200:] if result.stdout else "")
        else:
            err = result.stderr[-500:] if result.stderr else "(no stderr)"
            return (str(path), False, f"exit code {result.returncode}: {err}")
    except subprocess.TimeoutExpired:
        return (str(path), False, f"TIMEOUT after {TIMEOUT_SECONDS}s")
    except Exception as exc:
        return (str(path), False, f"ERROR: {exc}")


def main() -> None:
    base = Path(__file__).resolve().parent.parent
    all_files = find_py_files(base)

    if not all_files:
        print("未找到任何 Python 文件！")
        sys.exit(1)

    print(f"找到 {len(all_files)} 个 Python 文件\n")

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    started = time.perf_counter()

    for path in all_files:
        name, ok, msg = run_one(path, base)
        rel_path = str(Path(name).relative_to(base))

        if msg == "SKIPPED":
            print(f"  SKIP  {rel_path}")
            skipped += 1
        elif ok:
            print(f"  PASS  {rel_path}")
            passed += 1
        else:
            print(f"  FAIL  {rel_path}")
            failed += 1
            failures.append((rel_path, msg))

    elapsed = time.perf_counter() - started

    print(f"\n{'='*60}")
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过")
    print(f"耗时: {elapsed:.1f}s")

    if failures:
        print(f"\n失败详情:")
        for name, msg in failures:
            print(f"\n  {name}:")
            for line in msg.strip().split("\n"):
                print(f"    {line}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
