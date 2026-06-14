"""
Milvus 教程 smoke 测试

自动检查教程入口文档，并运行 examples/ 与 templates/ 下所有 Python 文件。
Milvus Lite 示例默认走本地 .db，不需要额外部署；smoke 会补齐 NO_PROXY/no_proxy。

运行方式（从 milvus教程/ 目录）：
    UV_CACHE_DIR=/tmp/uv-cache uv run python smoke/run_all_examples.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REQUIRED_FILES = {
    "README.md",
    "roadmap.md",
    "architecture_map.md",
    "best_practices.md",
    "pitfalls.md",
    "templates/README.md",
}

SKIP_FILES = {
    "__init__.py",
}

TIMEOUT_SECONDS = 90
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def find_py_files(base: Path) -> list[Path]:
    """递归查找 examples/ 和 templates/ 下所有 .py 文件。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        target = base / subdir
        if target.exists():
            files.extend(target.rglob("*.py"))
    return sorted(files)


def check_required_files(base: Path) -> list[str]:
    """检查教程入口文档是否齐全。"""
    missing: list[str] = []
    for rel_path in sorted(REQUIRED_FILES):
        if not (base / rel_path).exists():
            missing.append(rel_path)
    return missing


def command_cases(path: Path, base: Path) -> list[tuple[str, list[str]]]:
    """为示例选择运行方式；模板同时验证模块运行和直接文件运行。"""
    rel_path = path.relative_to(base)
    if rel_path.parts[0] == "templates":
        module_name = f"learning_common_lib.python基础.milvus教程.templates.{path.stem}"
        return [
            ("模块运行", [sys.executable, "-m", module_name]),
            ("文件运行", [sys.executable, str(path)]),
        ]
    return [("文件运行", [sys.executable, str(path)])]


def run_one(path: Path, base: Path, repo_root: Path, label: str, command: list[str]) -> tuple[str, str, str]:
    """运行单个示例，返回 (相对路径, 状态, 输出/错误信息)。"""
    rel_path = str(path.relative_to(base))
    display_name = f"{rel_path} [{label}]"

    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    env["NO_PROXY"] = merge_no_proxy(env.get("NO_PROXY", ""))
    env["no_proxy"] = merge_no_proxy(env.get("no_proxy", ""))

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=str(base),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return (rel_path, "失败", f"超过 {TIMEOUT_SECONDS} 秒仍未结束")
    except Exception as exc:
        return (rel_path, "失败", f"运行器异常: {exc}")

    output = (result.stdout or "") + (result.stderr or "")
    tail = output[-600:] if output else ""

    if result.returncode != 0:
        return (display_name, "失败", f"退出码 {result.returncode}: {tail}")
    return (display_name, "通过", tail)


def merge_no_proxy(current: str) -> str:
    """确保 Milvus Lite 的本机 gRPC 连接不会走代理。"""
    values = [item.strip() for item in current.split(",") if item.strip()]
    for item in LOCAL_NO_PROXY.split(","):
        if item not in values:
            values.append(item)
    return ",".join(values)


def main() -> None:
    base = Path(__file__).resolve().parent.parent
    repo_root = base.parents[3]
    missing = check_required_files(base)
    all_files = find_py_files(base)

    failures: list[tuple[str, str]] = []
    if missing:
        failures.extend((path, "缺少必备教程文件") for path in missing)

    if not all_files:
        failures.append(("examples/ 或 templates/", "未找到任何 Python 示例文件"))

    print(f"教程目录: {base}")
    print(f"发现 {len(all_files)} 个 Python 文件\n")

    passed = 0
    skipped = 0
    started = time.perf_counter()

    for path in all_files:
        if path.name in SKIP_FILES:
            skipped += 1
            print(f"  {'跳过':<4}  {path.relative_to(base)}")
            continue

        for label, command in command_cases(path, base):
            name, status, msg = run_one(path, base, repo_root, label, command)
            print(f"  {status:<4}  {name}")
            if status == "通过":
                passed += 1
            else:
                failures.append((name, msg))

    elapsed = time.perf_counter() - started

    print(f"\n{'=' * 60}")
    print(f"结果: {passed} 通过, {len(failures)} 失败, {skipped} 跳过")
    print(f"耗时: {elapsed:.1f}s")

    if failures:
        print("\n失败详情:")
        for name, msg in failures:
            print(f"\n  {name}:")
            for line in msg.strip().splitlines():
                print(f"    {line}")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
