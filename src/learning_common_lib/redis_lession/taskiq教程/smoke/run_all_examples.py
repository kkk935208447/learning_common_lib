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
    2. Redis 已启动（密码 123456），docker启动的，不存在 redis cli
    3. 本脚本会清空教程专用 Redis DB 0/1/2，避免不同示例互相污染

运行方式（从 src/learning_common_lib/redis_lession/taskiq教程 目录）：
    uv run python smoke/run_all_examples.py
"""

import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from hashlib import sha1
from pathlib import Path

import redis as redis_lib

SKIP_FILES = {
    "__init__.py",
    "清理redis的代码.py",
}

# 不需要 worker 的文件（纯配置演示或纯说明）
NO_WORKER_NEEDED = {
    "03_config_patterns.py",      # 纯配置演示
    "01_redis_schedule_source.py",  # 动态调度元数据演示
    "02_cron_and_interval.py",    # 纯调度配置演示
}

# 需要 FastAPI 的文件 — 只运行 main()（打印说明），不启动 uvicorn
FASTAPI_FILES = {
    "01_fastapi_taskiq.py",
    "02_fastapi_depends_shared.py",
}

EXAMPLE_TIMEOUT = 30
WORKER_STARTUP_WAIT = 3
WORKER_READY_TIMEOUT = 10

WORKER_ENTRYPOINTS = {
    "examples/09_broker_patterns/01_pubsub_broker.py": ["list_broker"],
    "examples/09_broker_patterns/02_multiple_queues.py": [
        "default_broker",
        "high_priority_broker",
        "batch_broker",
    ],
}

def reset_redis() -> None:
    """清空教程专用 Redis DB 0/1。"""
    for db in (0, 1, 2, 3):
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


def build_smoke_queue_name(rel_path: str, broker_name: str) -> str:
    """为 smoke 运行生成独立 queue_name，避免不同示例互相抢队列。"""
    normalized = rel_path.replace("\\", "/").removesuffix(".py").replace("/", ":")
    return f"smoke:{normalized}:{broker_name}"


def ensure_wrapper_module(
    module_path: str,
    rel_path: str,
    broker_names: list[str],
    wrapper_dir: Path,
) -> str:
    """生成临时 wrapper module，用于在 smoke 里注入独立 queue_name。"""
    wrapper_name = f"_smoke_{sha1(rel_path.encode('utf-8')).hexdigest()[:12]}"
    wrapper_file = wrapper_dir / f"{wrapper_name}.py"

    assignments: list[str] = []
    for broker_name in broker_names:
        queue_name = build_smoke_queue_name(rel_path, broker_name)
        assignments.extend(
            [
                f"{broker_name} = getattr(_orig, {broker_name!r})",
                f"if hasattr({broker_name}, 'queue_name'):",
                f"    {broker_name}.queue_name = {queue_name!r}",
                f"setattr(_orig, {broker_name!r}, {broker_name})",
            ]
        )

    wrapper_source = "\n".join(
        [
            "from __future__ import annotations",
            "import importlib as _importlib",
            f"_orig = _importlib.import_module({module_path!r})",
            *assignments,
            "main = getattr(_orig, 'main', None)",
            "app = getattr(_orig, 'app', None)",
            "scheduler = getattr(_orig, 'scheduler', None)",
        ]
    )
    wrapper_file.write_text(wrapper_source, encoding="utf-8")
    return wrapper_name


def wait_for_worker_ready(proc: subprocess.Popen, timeout: int) -> tuple[bool, str]:
    """等待 worker 输出 ready 日志。"""
    if proc.stdout is None:
        return False, "worker stdout 不可用"

    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    lines: list[str] = []
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break

            for key, _ in selector.select(timeout=0.5):
                line = key.fileobj.readline()
                if not line:
                    continue
                lines.append(line.rstrip())
                if "Listening started." in line:
                    return True, "\n".join(lines)
    finally:
        selector.close()

    return False, "\n".join(lines)


def start_worker(
    module_path: str,
    broker_name: str,
    base: Path,
    wrapper_dir: Path | None = None,
) -> tuple[subprocess.Popen | None, str]:
    """启动 taskiq worker 子进程并等待 ready。"""
    cmd = [
        sys.executable, "-m", "taskiq",
        "worker", f"{module_path}:{broker_name}",
        "--workers", "1",
    ]
    env = os.environ.copy()
    if wrapper_dir is not None:
        env["PYTHONPATH"] = (
            f"{wrapper_dir}{os.pathsep}{env['PYTHONPATH']}"
            if "PYTHONPATH" in env and env["PYTHONPATH"]
            else str(wrapper_dir)
        )
        cmd.extend(["--app-dir", str(wrapper_dir)])
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(base), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )
        ready, output = wait_for_worker_ready(proc, timeout=WORKER_READY_TIMEOUT)
        if ready:
            return proc, output
        stop_worker(proc)
        if output:
            return None, output
        return None, f"worker 在 {WORKER_READY_TIMEOUT}s 内未就绪"
    except Exception as exc:
        return None, str(exc)

def stop_worker(proc: subprocess.Popen) -> None:
    """停止 worker 子进程。"""
    if proc is None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        pass
    finally:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def cleanup_taskiq_example_workers(base: Path) -> None:
    """兜底清理可能残留的 tutorial worker 进程。"""
    try:
        subprocess.run(
            ["pkill", "-9", "-f", "taskiq worker examples."],
            cwd=str(base),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def run_example(
    file_path: Path,
    base: Path,
    wrapper_module: str | None = None,
    wrapper_dir: Path | None = None,
) -> tuple[bool, str]:
    """运行单个 example 脚本，返回 (成功, 输出/错误信息)。"""
    env = os.environ.copy()
    if wrapper_module is None:
        relative_path = str(file_path.relative_to(base))
        cmd = [sys.executable, relative_path]
    else:
        if wrapper_dir is None:
            raise ValueError("wrapper_module 存在时，wrapper_dir 不能为空")
        env["PYTHONPATH"] = (
            f"{wrapper_dir}{os.pathsep}{env['PYTHONPATH']}"
            if "PYTHONPATH" in env and env["PYTHONPATH"]
            else str(wrapper_dir)
        )
        code = (
            "import asyncio, importlib, inspect\n"
            f"mod = importlib.import_module({wrapper_module!r})\n"
            "main = getattr(mod, 'main', None)\n"
            "if main is None:\n"
            "    raise SystemExit('main() not found')\n"
            "result = main()\n"
            "if inspect.isawaitable(result):\n"
            "    asyncio.run(result)\n"
        )
        cmd = [sys.executable, "-c", code]
    try:
        result = subprocess.run(
            cmd, cwd=str(base), env=env, capture_output=True, text=True,
            timeout=EXAMPLE_TIMEOUT,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"超时 ({EXAMPLE_TIMEOUT}s)"
    except Exception as exc:
        return False, str(exc)


def run_one(
    file_path: Path,
    base: Path,
    wrapper_dir: Path,
) -> tuple[str, bool, str]:
    """运行单个示例（含 worker 管理）。"""
    rel_path = str(file_path.relative_to(base))
    module_path = get_module_path(file_path, base)
    rel_path_posix = rel_path.replace("\\", "/")

    if file_path.name in SKIP_FILES:
        return rel_path, True, "SKIPPED"

    needs_worker = file_path.name not in NO_WORKER_NEEDED
    is_fastapi = file_path.name in FASTAPI_FILES

    # FastAPI 文件：只运行 main()（打印说明），不启动 worker
    if is_fastapi:
        needs_worker = False

    worker_procs: list[subprocess.Popen] = []
    wrapper_module: str | None = None
    if needs_worker:
        cleanup_taskiq_example_workers(base)
        broker_names = WORKER_ENTRYPOINTS.get(rel_path_posix, ["broker"])
        wrapper_module = ensure_wrapper_module(
            module_path=module_path,
            rel_path=rel_path_posix,
            broker_names=broker_names,
            wrapper_dir=wrapper_dir,
        )
        for broker_name in broker_names:
            worker_proc, worker_output = start_worker(
                wrapper_module,
                broker_name,
                base,
                wrapper_dir=wrapper_dir,
            )
            if worker_proc is None:
                return rel_path, False, f"Worker 启动失败: {broker_name}\n{worker_output}"
            worker_procs.append(worker_proc)
        time.sleep(WORKER_STARTUP_WAIT)

    try:
        ok, output = run_example(
            file_path,
            base,
            wrapper_module=wrapper_module,
            wrapper_dir=wrapper_dir,
        )
        return rel_path, ok, output
    finally:
        for worker_proc in reversed(worker_procs):
            stop_worker(worker_proc)
        cleanup_taskiq_example_workers(base)
        # 每个示例后清理 Redis，避免互相污染
        try:
            reset_redis()
        except Exception:
            pass

def main() -> None:
    """运行所有示例，报告结果。"""
    base = Path(__file__).resolve().parent.parent
    wrapper_dir = Path(tempfile.mkdtemp(prefix="taskiq_smoke_wrappers_"))

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
        name, ok, msg = run_one(path, base, wrapper_dir)

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
