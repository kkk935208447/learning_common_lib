"""
exception 教程 smoke 测试

自动发现并运行 examples/ 和 templates/ 下所有示例文件，验证模块自洽。
只依赖本模块，不依赖项目其他部分。

运行方式（从 exception教程/ 目录）：
    uv run python smoke/run_all_examples.py
"""

import subprocess
import sys
import time
from pathlib import Path

SKIP_FILES = {
    "__init__.py",
}

TIMEOUT_SECONDS = 30  # FastAPI examples may need more time


def find_py_files(base: Path) -> list[Path]:
    """递归查找 examples/ 和 templates/ 下所有 .py 文件，按路径排序。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        d = base / subdir
        if d.exists():
            files.extend(d.rglob("*.py"))
    return sorted(files)


def run_one(path: Path) -> tuple[str, bool, str]:
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
        )
        if result.returncode == 0:
            return (str(path), True, result.stdout[-200:] if result.stdout else "")
        else:
            err = result.stderr[-300:] if result.stderr else "(no stderr)"
            return (str(path), False, f"exit code {result.returncode}: {err}")
    except subprocess.TimeoutExpired:
        return (str(path), False, f"TIMEOUT after {TIMEOUT_SECONDS}s")
    except Exception as exc:
        return (str(path), False, f"ERROR: {exc}")


def main() -> None:
    base = Path(__file__).resolve().parent.parent
    all_files = find_py_files(base)

    if not all_files:
        print("No Python files found!")
        sys.exit(1)

    print(f"Found {len(all_files)} Python files\n")

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    started = time.perf_counter()

    for path in all_files:
        name, ok, msg = run_one(path)
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
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"Time: {elapsed:.1f}s")

    if failures:
        print(f"\nFailures:")
        for name, msg in failures:
            print(f"\n  {name}:")
            for line in msg.strip().split("\n"):
                print(f"    {line}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
