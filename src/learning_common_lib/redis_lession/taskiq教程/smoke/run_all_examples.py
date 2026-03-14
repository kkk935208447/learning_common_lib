"""
TaskIQ 教程 smoke 测试

对每个 example 文件:
  1. 启动 worker 子进程
  2. 等待 worker 就绪
  3. 运行 example 脚本
  4. 杀掉 worker
  5. 报告 PASS/FAIL

前置条件：
    1. taskiq-redis 已安装（uv sync）
    2. Redis 已启动（密码 123456）
    3. 本脚本会清空教程专用 Redis DB 0/1，避免不同示例互相污染

运行方式（从 src/learning_common_lib/redis_lession/taskiq教程 目录）：
    uv run python smoke/run_all_examples.py
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import redis as redis_lib

SKIP_FILES = {
    "__init__.py",
    "清理redis的代码.py",
}

# 不需要 worker 的文件（纯配置演示或纯说明）
NO_WORKER_NEEDED = {
    "03_config_patterns.py",      # 纯配置演示
    "02_cron_and_interval.py",    # 纯调度配置演示
}

# 需要 FastAPI 的文件 — 只运行 main()（打印说明），不启动 uvicorn
FASTAPI_FILES = {
    "01_fastapi_taskiq.py",
    "02_fastapi_depends_shared.py",
}

EXAMPLE_TIMEOUT = 30
WORKER_STARTUP_WAIT = 3

def reset_redis() -> None:
    """清空教程专用 Redis DB 0/1。"""
    for db in (0, 1):
        client = redis_lib.Redis(
            host="localhost", port=6379, password="123456",
            db=db, socket_connect_timeout=3,
        )
        try:
            client.flushdb()
        finally:
            client.close()


def check_redis() -> bool:
    """检查 Redis 是否可用。"""
    try:
        client = redis_lib.Redis(
            host="localhost", port=6379, password="123456",
            db=0, socket_connect_timeout=3,
        )
        client.ping()
        client.close()
        return True
    except Exception:
        return False


def collect_examples(base: Path) -> list[Path]:
    """收集所有 example Python 文件，按路径排序。"""
    examples_dir = base / "examples"
    files = sorted(examples_dir.rglob("*.py"))
    return [f for f in files if f.name not in SKIP_FILES]


def get_module_path(file_path: Path, base: Path) -> str:
    """将文件路径转换为 Python 模块路径（不含 .py）。"""
    rel = file_path.relative_to(base)
    return str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")


def start_worker(module_path: str, base: Path) -> subprocess.Popen | None:
    """启动 taskiq worker 子进程。"""
    cmd = [
        sys.executable, "-m", "taskiq",
        "worker", f"{module_path}:broker",
    ]
    env = os.environ.copy()
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(base), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        time.sleep(WORKER_STARTUP_WAIT)
        return proc
    except Exception as exc:
        print(f"    ⚠️ Worker 启动失败: {exc}", flush=True)
        return None

def stop_worker(proc: subprocess.Popen) -> None:
    """停止 worker 子进程。"""
    if proc is None:
        return
    try:
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass


def run_example(file_path: Path, base: Path) -> tuple[bool, str]:
    """运行单个 example 脚本，返回 (成功, 输出/错误信息)。"""
    cmd = [sys.executable, str(file_path)]
    try:
        result = subprocess.run(
            cmd, cwd=str(base), capture_output=True, text=True,
            timeout=EXAMPLE_TIMEOUT,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"超时 ({EXAMPLE_TIMEOUT}s)"
    except Exception as exc:
        return False, str(exc)


def run_one(file_path: Path, base: Path) -> tuple[str, bool, str]:
    """运行单个示例（含 worker 管理）。"""
    rel_path = str(file_path.relative_to(base))
    module_path = get_module_path(file_path, base)

    if file_path.name in SKIP_FILES:
        return rel_path, True, "SKIPPED"

    needs_worker = file_path.name not in NO_WORKER_NEEDED
    is_fastapi = file_path.name in FASTAPI_FILES

    # FastAPI 文件：只运行 main()（打印说明），不启动 worker
    if is_fastapi:
        needs_worker = False

    worker_proc = None
    if needs_worker:
        worker_proc = start_worker(module_path, base)
        if worker_proc is None:
            return rel_path, False, "Worker 启动失败"

    try:
        ok, output = run_example(file_path, base)
        return rel_path, ok, output
    finally:
        if worker_proc:
            stop_worker(worker_proc)
        # 每个示例后清理 Redis，避免互相污染
        try:
            reset_redis()
        except Exception:
            pass

def main() -> None:
    """运行所有示例，报告结果。"""
    base = Path(__file__).resolve().parent.parent

    if not check_redis():
        print("❌ Redis 不可用，请确保 Redis 已启动（密码 123456）", flush=True)
        sys.exit(1)

    print("🧹 清理 Redis DB 0/1...", flush=True)
    reset_redis()

    all_files = collect_examples(base)
    print(f"找到 {len(all_files)} 个 Python 文件\n", flush=True)

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    started = time.perf_counter()

    for path in all_files:
        rel_path = str(path.relative_to(base))
        print(f"RUN   {rel_path}", flush=True)
        name, ok, msg = run_one(path, base)

        if msg == "SKIPPED":
            print(f"  SKIP  {name}", flush=True)
            skipped += 1
        elif ok:
            worker_label = " (w/ worker)" if path.name not in NO_WORKER_NEEDED and path.name not in FASTAPI_FILES else ""
            print(f"  PASS  {name}{worker_label}", flush=True)
            passed += 1
        else:
            print(f"  FAIL  {name}", flush=True)
            failed += 1
            failures.append((name, msg))

    elapsed = time.perf_counter() - started

    print(f"\n{'='*60}", flush=True)
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过", flush=True)
    print(f"耗时: {elapsed:.1f}s", flush=True)

    if failures:
        print(f"\n失败详情:", flush=True)
        for name, msg in failures:
            print(f"\n  {name}:", flush=True)
            for line in msg.strip().split("\n")[-10:]:
                print(f"    {line}", flush=True)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
