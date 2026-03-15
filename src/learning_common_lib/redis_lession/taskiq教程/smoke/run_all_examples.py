"""
TaskIQ 教程 smoke 测试

对每个 example / template 文件：
  1. 按需启动 worker 子进程
  2. 等待 worker 就绪
  3. 直接运行脚本文件
  4. 停掉当前文件关联的 worker 进程组
  5. 报告 PASS/FAIL

设计说明：
    1. 运行结构尽量贴近 celery教程与Redlock/smoke/run_all_examples.py
    2. 不使用临时 wrapper module，不注入虚拟包裹
    3. TaskIQ + Redis ListQueueBroker 是“先竞争消费，再按 task_name 找函数”
       同一组同构 worker 共享一个 queue_name 是正常模式；
       真正危险的是任务注册集合不一致的 worker 共享同一个 queue_name
    4. 为避免误消费，smoke 会通过环境变量为每个案例注入独立 queue_name
    5. worker 使用独立进程组启动，并在每轮结束后做 TERM/KILL 双阶段回收

前置条件：
    1. taskiq-redis 已安装（uv sync）
    2. Redis 已启动（密码 123456）
    3. 本脚本会清空教程专用 Redis DB 0/1/2/3，避免不同示例互相污染

运行方式（从 src/learning_common_lib/redis_lession/taskiq教程 目录）：
    uv run python smoke/run_all_examples.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import redis as redis_lib

SKIP_FILES = {
    "__init__.py",
    "清理redis的代码.py",
}

NO_WORKER_NEEDED = {
    "examples/01_broker_and_config/03_config_patterns.py",
    "examples/07_scheduling/01_redis_schedule_source.py",
    "examples/07_scheduling/02_cron_and_interval.py",
    "examples/10_fastapi_integration/01_fastapi_taskiq.py",
    "examples/10_fastapi_integration/02_fastapi_depends_shared.py",
}

EXAMPLE_TIMEOUT = 30
WORKER_READY_TIMEOUT = 12
WORKER_STARTUP_WAIT = 2
WORKER_STOP_TIMEOUT = 8
WORKER_KILL_TIMEOUT = 5

EXAMPLE_TIMEOUT_OVERRIDES = {
    "examples/05_middlewares/03_retry_middleware.py": 40,
    "examples/06_error_handling/01_reject_and_requeue.py": 40,
    "examples/06_error_handling/02_smart_retry_with_backoff.py": 45,
}

WORKER_SPECS = {
    "examples/09_broker_patterns/01_pubsub_broker.py": [
        {"entrypoint": "list_broker"},
    ],
    "examples/09_broker_patterns/02_multiple_queues.py": [
        {"entrypoint": "default_broker"},
        {"entrypoint": "high_priority_broker"},
        {"entrypoint": "batch_broker"},
    ],
}

QUEUE_ENV_ENTRYPOINTS = {
    "examples/09_broker_patterns/01_pubsub_broker.py": [
        "list_broker",
        "pubsub_broker",
    ],
    "examples/09_broker_patterns/02_multiple_queues.py": [
        "default_broker",
        "high_priority_broker",
        "batch_broker",
    ],
}


def find_py_files(base: Path) -> list[Path]:
    """递归查找 examples/ 和 templates/ 下所有 .py 文件，按路径排序。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        directory = base / subdir
        if directory.exists():
            files.extend(directory.rglob("*.py"))
    return sorted(path for path in files if path.name not in SKIP_FILES)


def get_module_path(path: Path, base: Path) -> str:
    """将文件路径转为 Python 模块路径。"""
    rel = path.relative_to(base)
    return str(rel.with_suffix("")).replace(os.sep, ".")


def get_worker_specs(path: Path, base: Path) -> list[dict[str, object]]:
    """按示例文件返回 worker 规格。"""
    rel_path = str(path.relative_to(base)).replace(os.sep, "/")
    if rel_path.startswith("templates/"):
        return []
    if rel_path in NO_WORKER_NEEDED:
        return []
    return WORKER_SPECS.get(rel_path, [{"entrypoint": "broker"}])


def needs_worker(path: Path, base: Path) -> bool:
    """判断文件是否需要启动 worker。"""
    return bool(get_worker_specs(path, base))


def get_example_timeout(path: Path, base: Path) -> int:
    """按文件路径返回示例超时时间。"""
    rel_path = str(path.relative_to(base)).replace(os.sep, "/")
    return EXAMPLE_TIMEOUT_OVERRIDES.get(rel_path, EXAMPLE_TIMEOUT)


def reset_tutorial_redis() -> None:
    """清空教程专用 Redis DB，避免示例之间互相污染。"""
    for db in (0, 1, 2, 3):
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


def check_redis() -> bool:
    """检查 Redis 是否可用。"""
    try:
        client = redis_lib.Redis(
            host="localhost",
            port=6379,
            password="123456",
            db=0,
            socket_connect_timeout=3,
        )
        client.ping()
        client.close()
        return True
    except Exception:
        return False


def normalize_env_suffix(name: str) -> str:
    """把 broker 名规范化为环境变量后缀。"""
    chars: list[str] = []
    for char in name:
        if char.isalnum():
            chars.append(char.upper())
        else:
            chars.append("_")
    return "".join(chars)


def build_smoke_queue_name(rel_path: str, broker_name: str) -> str:
    """为 smoke 运行生成独立 queue_name。"""
    normalized = rel_path.removesuffix(".py").replace("/", ":")
    run_id = f"{os.getpid()}:{int(time.time() * 1000)}"
    return f"smoke:{run_id}:{normalized}:{broker_name}"


def build_queue_env(path: Path, base: Path, worker_specs: list[dict[str, object]]) -> dict[str, str]:
    """为当前案例构建 queue_name 覆盖环境变量。"""
    rel_path = str(path.relative_to(base)).replace(os.sep, "/")
    env: dict[str, str] = {}

    if not worker_specs:
        return env

    override_entrypoints = QUEUE_ENV_ENTRYPOINTS.get(rel_path)
    if override_entrypoints is not None:
        for entrypoint in override_entrypoints:
            env_key = f"TASKIQ_QUEUE_NAME_{normalize_env_suffix(entrypoint)}"
            env[env_key] = build_smoke_queue_name(rel_path, entrypoint)
        return env

    if len(worker_specs) == 1 and str(worker_specs[0].get("entrypoint", "broker")) == "broker":
        env["TASKIQ_QUEUE_NAME"] = build_smoke_queue_name(rel_path, "broker")
        return env

    for spec in worker_specs:
        entrypoint = str(spec.get("entrypoint", "broker"))
        env_key = f"TASKIQ_QUEUE_NAME_{normalize_env_suffix(entrypoint)}"
        env[env_key] = build_smoke_queue_name(rel_path, entrypoint)
    return env


def read_log_tail(log_path: Path, max_chars: int = 4000) -> str:
    """读取日志尾部，便于失败诊断。"""
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    if len(content) <= max_chars:
        return content
    return content[-max_chars:]


def cleanup_taskiq_workers(module: str, entrypoint: str, base: Path) -> None:
    """按模块和 broker 入口兜底清理残留 worker。"""
    pattern = f"taskiq worker {module}:{entrypoint}"
    commands = [
        ["pkill", "-TERM", "-f", pattern],
        ["pkill", "-KILL", "-f", pattern],
    ]
    for command in commands:
        try:
            subprocess.run(
                command,
                cwd=str(base),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass


def wait_for_worker_ready(proc: subprocess.Popen[bytes], log_path: Path) -> tuple[bool, str]:
    """等待 worker 日志出现 ready 标记。"""
    deadline = time.monotonic() + WORKER_READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False, read_log_tail(log_path)
        if "Listening started." in read_log_tail(log_path, max_chars=12000):
            time.sleep(WORKER_STARTUP_WAIT)
            return True, ""
        time.sleep(0.2)
    return False, read_log_tail(log_path)


def start_worker(
    module: str,
    base: Path,
    spec: dict[str, object],
    extra_env: dict[str, str],
    log_dir: Path,
) -> tuple[subprocess.Popen[bytes] | None, Path, str]:
    """启动 TaskIQ worker 子进程。"""
    entrypoint = str(spec.get("entrypoint", "broker"))
    log_path = log_dir / f"{module.replace('.', '_')}__{entrypoint}.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        cmd = [
            sys.executable,
            "-m",
            "taskiq",
            "worker",
            f"{module}:{entrypoint}",
            "--workers",
            "1",
            "--log-level",
            "INFO",
        ]
        env = os.environ.copy()
        env.update(extra_env)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(base),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as exc:
            return None, log_path, str(exc)

    ready, detail = wait_for_worker_ready(proc, log_path)
    if ready:
        return proc, log_path, ""

    stop_worker(proc)
    return None, log_path, detail or f"worker 在 {WORKER_READY_TIMEOUT}s 内未就绪"


def stop_worker(proc: subprocess.Popen[bytes]) -> None:
    """停止 worker 主进程及其派生子进程。"""
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = None

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=WORKER_STOP_TIMEOUT)
        return
    except Exception:
        pass

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=WORKER_KILL_TIMEOUT)
    except Exception:
        pass


def run_python_file(
    path: Path,
    base: Path,
    timeout: int,
    extra_env: dict[str, str],
) -> tuple[bool, str]:
    """直接运行 Python 文件。"""
    env = os.environ.copy()
    env.update(extra_env)
    try:
        result = subprocess.run(
            [sys.executable, str(path.relative_to(base))],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(base),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    except Exception as exc:
        return False, f"ERROR: {exc}"

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        return True, output[-500:] if output else ""
    return False, f"exit code {result.returncode}: {output[-1000:] if output else '(no output)'}"


def run_one(path: Path, base: Path, log_dir: Path) -> tuple[str, bool, str]:
    """运行单个示例，返回 (文件名, 是否成功, 输出/错误信息)。"""
    rel_path = str(path.relative_to(base)).replace(os.sep, "/")
    if path.name in SKIP_FILES:
        return rel_path, True, "SKIPPED"

    worker_specs = get_worker_specs(path, base)
    queue_env = build_queue_env(path, base, worker_specs)
    worker_handles: list[tuple[subprocess.Popen[bytes], str, Path]] = []
    worker_logs_to_delete: list[Path] = []
    module = get_module_path(path, base)

    try:
        reset_tutorial_redis()
        timeout = get_example_timeout(path, base)

        for spec in worker_specs:
            entrypoint = str(spec.get("entrypoint", "broker"))
            cleanup_taskiq_workers(module, entrypoint, base)
            proc, log_path, detail = start_worker(
                module=module,
                base=base,
                spec=spec,
                extra_env=queue_env,
                log_dir=log_dir,
            )
            worker_logs_to_delete.append(log_path)
            if proc is None:
                return rel_path, False, f"Worker 启动失败: {entrypoint}\n{detail}"
            worker_handles.append((proc, entrypoint, log_path))

        ok, output = run_python_file(path, base, timeout, queue_env)
        return rel_path, ok, output
    finally:
        for proc, entrypoint, _ in reversed(worker_handles):
            stop_worker(proc)
            cleanup_taskiq_workers(module, entrypoint, base)
        for log_path in worker_logs_to_delete:
            try:
                log_path.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            reset_tutorial_redis()
        except Exception:
            pass


def main() -> None:
    base = Path(__file__).resolve().parent.parent
    all_files = find_py_files(base)

    if not all_files:
        print("未找到任何 Python 文件！")
        sys.exit(1)

    print("验证 Redis 连接...", flush=True)
    if not check_redis():
        print("Redis 不可用，请确保 Redis 已启动（密码 123456）", flush=True)
        sys.exit(1)
    print("✅ Redis 连接正常\n", flush=True)

    print("🧹 清理 Redis DB 0/1/2/3...", flush=True)
    reset_tutorial_redis()

    log_dir_path = Path(tempfile.mkdtemp(prefix="taskiq_smoke_logs_"))
    print(f"找到 {len(all_files)} 个 Python 文件\n", flush=True)

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    started = time.perf_counter()

    try:
        for path in all_files:
            rel_path = str(path.relative_to(base)).replace(os.sep, "/")
            print(f"RUN   {rel_path}", flush=True)
            name, ok, msg = run_one(path, base, log_dir_path)

            if msg == "SKIPPED":
                print(f"  SKIP  {name}", flush=True)
                skipped += 1
            elif ok:
                worker_specs = get_worker_specs(path, base)
                worker_count = len(worker_specs)
                label = "workers" if worker_count != 1 else "worker"
                suffix = f" (w/ {worker_count} {label})" if worker_specs else ""
                print(f"  PASS  {name}{suffix}", flush=True)
                passed += 1
            else:
                print(f"  FAIL  {name}", flush=True)
                failed += 1
                failures.append((name, msg))
    finally:
        try:
            reset_tutorial_redis()
        except Exception:
            pass
        for log_path in log_dir_path.glob("*"):
            try:
                log_path.unlink()
            except Exception:
                pass
        try:
            log_dir_path.rmdir()
        except Exception:
            pass

    elapsed = time.perf_counter() - started

    print(f"\n{'=' * 60}", flush=True)
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过", flush=True)
    print(f"耗时: {elapsed:.1f}s", flush=True)

    if failures:
        print("\n失败详情:", flush=True)
        for name, msg in failures:
            print(f"\n  {name}:", flush=True)
            for line in msg.strip().splitlines()[-20:]:
                print(f"    {line}", flush=True)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
