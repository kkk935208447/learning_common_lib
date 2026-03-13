"""
Celery 教程与 Redis 分布式锁 smoke 测试

对每个 example 文件:
  1. 启动 worker 子进程
  2. 等待 worker 就绪
  3. 运行 example 脚本
  4. 杀掉 worker
  5. 报告 PASS/FAIL

前置条件：
    1. celery[redis] 已安装（uv sync）
    2. Redis 已启动（密码 123456）
    3. 本脚本会清空教程专用 Redis DB 0/1，避免不同示例互相污染

运行方式（从 src/learning_common_lib/redis_lession/celery教程与Redlock 目录）：
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
    "redlock.py",  # 历史兼容别名，不单独作为模板 demo 运行
}

# 不需要 worker 的文件（只读配置、只定义 beat_schedule、或纯演示）
NO_WORKER_NEEDED = {
    "02_config_patterns.py",     # 只读配置，不调度任务
    "02_distributed_lock.py",  # 只演示 Redis 锁，不提交 Celery 任务
}

EXAMPLE_TIMEOUT = 60
WORKER_STARTUP_WAIT = 5

EXAMPLE_TIMEOUT_OVERRIDES = {
    "03_watchdog_lock_with_celery.py": 90,
}


def find_py_files(base: Path) -> list[Path]:
    """递归查找 examples/ 和 templates/ 下所有 .py 文件，按路径排序。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        d = base / subdir
        if d.exists():
            files.extend(d.rglob("*.py"))
    return sorted(files)


def get_celery_module(path: Path, base: Path) -> str:
    """将文件路径转为 Celery -A 参数的模块路径。

    例如: examples/01_app_and_config/01_celery_hello.py
        → examples.01_app_and_config.01_celery_hello
    """
    rel = path.relative_to(base)
    # 去掉 .py 后缀，用 . 连接
    return str(rel.with_suffix("")).replace(os.sep, ".")


def needs_worker(path: Path) -> bool:
    """判断文件是否需要启动 worker。"""
    # template 文件不需要 worker（它们的 _demo 自行处理）
    if "templates" in path.parts:
        return False
    # 特定文件不需要 worker
    if path.name in NO_WORKER_NEEDED:
        return False
    return True


def start_worker(module: str, base: Path, queues: str | None = None) -> subprocess.Popen:
    """启动 Celery worker 子进程。"""
    cmd = [
        sys.executable, "-m", "celery",
        "-A", module,
        "worker",
        "-l", "error",
        "-P", "solo",
    ]
    if queues:
        cmd.extend(["-Q", queues])

    return subprocess.Popen(
        cmd,
        cwd=str(base),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def get_worker_queues(path: Path) -> str | None:
    """某些文件需要 worker 消费特定队列。"""
    if path.name == "01_task_queues.py":
        return "default,email_queue,report_queue,notification_queue"
    if path.name == "01_delay_and_apply_async.py":
        return "default,high_priority,greetings"
    if path.name == "02_signatures.py":
        return "default,math_queue"
    return None


def get_example_timeout(path: Path) -> int:
    """按文件名返回示例超时时间。"""
    return EXAMPLE_TIMEOUT_OVERRIDES.get(path.name, EXAMPLE_TIMEOUT)


def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2):
        client = redis_lib.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=db,
            socket_connect_timeout=3,
        )
        try:
            client.flushdb()
        finally:
            client.close()


def run_one(path: Path, base: Path) -> tuple[str, bool, str]:
    """运行单个示例，返回 (文件名, 是否成功, 输出/错误信息)。"""
    rel = path.name
    if rel in SKIP_FILES:
        return (str(path), True, "SKIPPED")

    worker_proc = None
    try:
        reset_tutorial_redis()
        timeout = get_example_timeout(path)

        if needs_worker(path):
            module = get_celery_module(path, base)
            queues = get_worker_queues(path)
            worker_proc = start_worker(module, base, queues)
            # 等待 worker 启动
            time.sleep(WORKER_STARTUP_WAIT)

            # 检查 worker 是否已崩溃
            if worker_proc.poll() is not None:
                stderr = worker_proc.stderr.read().decode() if worker_proc.stderr else ""
                return (str(path), False, f"Worker 启动失败: {stderr[-500:]}")

        # 运行示例脚本
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(base),
        )

        if result.returncode == 0:
            return (str(path), True, result.stdout[-200:] if result.stdout else "")
        else:
            err = result.stderr[-500:] if result.stderr else "(no stderr)"
            return (str(path), False, f"exit code {result.returncode}: {err}")

    except subprocess.TimeoutExpired:
        return (str(path), False, f"TIMEOUT after {timeout}s")
    except Exception as exc:
        return (str(path), False, f"ERROR: {exc}")
    finally:
        if worker_proc is not None:
            try:
                worker_proc.send_signal(signal.SIGTERM)
                worker_proc.wait(timeout=10)
            except Exception:
                worker_proc.kill()
                worker_proc.wait(timeout=5)
        reset_tutorial_redis()


def main() -> None:
    base = Path(__file__).resolve().parent.parent
    all_files = find_py_files(base)

    if not all_files:
        print("未找到任何 Python 文件！")
        sys.exit(1)

    # 验证 Redis 连接
    print("验证 Redis 连接...", flush=True)
    try:
        r = redis_lib.Redis(host="localhost", port=6379, password="123456", db=0, socket_connect_timeout=3)
        r.ping()
        print("✅ Redis 连接正常\n", flush=True)
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}", flush=True)
        print("请确保 Redis 已启动（密码 123456）", flush=True)
        sys.exit(1)

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
        rel_path = str(Path(name).relative_to(base))

        if msg == "SKIPPED":
            print(f"  SKIP  {rel_path}", flush=True)
            skipped += 1
        elif ok:
            w = " (w/ worker)" if needs_worker(path) else ""
            print(f"  PASS  {rel_path}{w}", flush=True)
            passed += 1
        else:
            print(f"  FAIL  {rel_path}", flush=True)
            failed += 1
            failures.append((rel_path, msg))

    elapsed = time.perf_counter() - started

    print(f"\n{'='*60}", flush=True)
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过", flush=True)
    print(f"耗时: {elapsed:.1f}s", flush=True)

    if failures:
        print(f"\n失败详情:", flush=True)
        for name, msg in failures:
            print(f"\n  {name}:", flush=True)
            for line in msg.strip().split("\n"):
                print(f"    {line}", flush=True)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
