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
    2. gevent / celery-aio-pool 已安装（第 4 章 worker 对比示例需要）
    3. Redis 已启动（密码 123456）
    4. 本脚本会清空教程专用 Redis DB 0/1/2，避免不同示例互相污染

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
    "04_sync_vs_greenlet_vs_asyncio.py",  # 纯对比总结脚本
}

EXAMPLE_TIMEOUT = 60
WORKER_STARTUP_WAIT = 5
PREFORK_STARTUP_WAIT = 8
GREENLET_STARTUP_WAIT = 8
CUSTOM_POOL_STARTUP_WAIT = 8

EXAMPLE_TIMEOUT_OVERRIDES = {
    "02_official_greenlet_pools.py": 90,
    "05_mixed_deployment_patterns.py": 90,
    "03_watchdog_lock_with_celery.py": 120,
}

ASYNCIO_POOL_CLASS = "celery_aio_pool.pool:AsyncIOPool"

WORKER_SPECS = {
    "examples/03_task_invocation/01_delay_and_apply_async.py": [
        {"queues": "default,high_priority,greetings"},
    ],
    "examples/03_task_invocation/02_signatures.py": [
        {"queues": "default,math_queue"},
    ],
    "examples/04_async_worker_tasks/01_sync_worker_baseline.py": [
        {
            "queues": "prefork_jobs",
            "pool": "prefork",
            "concurrency": 2,
            "startup_wait": PREFORK_STARTUP_WAIT,
        },
    ],
    "examples/04_async_worker_tasks/02_official_greenlet_pools.py": [
        {
            "queues": "prefork_jobs",
            "pool": "prefork",
            "concurrency": 2,
            "startup_wait": PREFORK_STARTUP_WAIT,
        },
        {
            "queues": "greenlet_jobs",
            "pool": "gevent",
            "concurrency": 20,
            "startup_wait": GREENLET_STARTUP_WAIT,
        },
    ],
    "examples/04_async_worker_tasks/03_custom_aio_pool_async_task.py": [
        {
            "queues": "aio_jobs",
            "pool": "custom",
            "concurrency": 20,
            "startup_wait": CUSTOM_POOL_STARTUP_WAIT,
            "env": {"CELERY_CUSTOM_WORKER_POOL": ASYNCIO_POOL_CLASS},
        },
    ],
    "examples/04_async_worker_tasks/05_mixed_deployment_patterns.py": [
        {
            "queues": "prefork_jobs",
            "pool": "prefork",
            "concurrency": 2,
            "startup_wait": PREFORK_STARTUP_WAIT,
        },
        {
            "queues": "aio_jobs",
            "pool": "custom",
            "concurrency": 20,
            "startup_wait": CUSTOM_POOL_STARTUP_WAIT,
            "env": {"CELERY_CUSTOM_WORKER_POOL": ASYNCIO_POOL_CLASS},
        },
    ],
    "examples/07_routing_and_queues/01_task_queues.py": [
        {"queues": "default,email_queue,report_queue,notification_queue"},
    ],
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


def get_worker_specs(path: Path, base: Path) -> list[dict[str, object]]:
    """按示例文件返回 worker 规格。"""
    # template 文件不需要 worker（它们的 _demo 自行处理）
    if "templates" in path.parts:
        return []
    # 特定文件不需要 worker
    if path.name in NO_WORKER_NEEDED:
        return []
    rel_path = str(path.relative_to(base))
    return WORKER_SPECS.get(rel_path, [{}])


def needs_worker(path: Path, base: Path) -> bool:
    """判断文件是否需要启动 worker。"""
    return bool(get_worker_specs(path, base))


def start_worker(module: str, base: Path, spec: dict[str, object]) -> subprocess.Popen:
    """启动 Celery worker 子进程。"""
    pool = str(spec.get("pool", "solo"))
    concurrency = spec.get("concurrency")
    cmd = [
        sys.executable, "-m", "celery",
        "-A", module,
        "worker",
        "-l", "error",
        "-P", pool,
    ]
    if concurrency:
        cmd.extend(["-c", str(concurrency)])
    queues = spec.get("queues")
    if queues:
        cmd.extend(["-Q", str(queues)])

    env = os.environ.copy()
    env.update({k: str(v) for k, v in dict(spec.get("env", {})).items()})

    return subprocess.Popen(
        cmd,
        cwd=str(base),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


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

    worker_procs: list[subprocess.Popen] = []
    try:
        reset_tutorial_redis()
        timeout = get_example_timeout(path)

        if needs_worker(path, base):
            module = get_celery_module(path, base)
            worker_specs = get_worker_specs(path, base)
            for spec in worker_specs:
                proc = start_worker(module, base, spec)
                worker_procs.append(proc)
                time.sleep(int(spec.get("startup_wait", WORKER_STARTUP_WAIT)))
                if proc.poll() is not None:
                    stderr = proc.stderr.read().decode() if proc.stderr else ""
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
        for proc in reversed(worker_procs):
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
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
            worker_specs = get_worker_specs(path, base)
            worker_count = len(worker_specs)
            label = "workers" if worker_count != 1 else "worker"
            w = f" (w/ {worker_count} {label})" if worker_specs else ""
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
