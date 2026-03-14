"""
TaskIQ 教程 smoke 测试。

统一验证 examples/ 与 templates/ 下所有 Python 文件：
  1. 为需要 worker 的示例启动独立 worker 子进程
  2. 使用独立 queue_name 隔离 smoke 流量，避免抢占真实教程队列
  3. 运行 example 的 main() 或 template 的 _demo()
  4. 停止当前文件关联的 worker
  5. 报告 PASS/FAIL/SKIP

前置条件：
    1. taskiq-redis 已安装（uv sync）
    2. Redis 已启动（密码 123456），docker启动的，不存在 redis cli
    3. 本脚本会清空教程专用 Redis DB 0/1/2，避免不同示例互相污染

运行方式（从 src/learning_common_lib/redis_lession/taskiq教程 目录）：
    uv run python smoke/run_all_examples.py
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Literal

import redis as redis_lib

SKIP_FILES = {
    "__init__.py",
    "清理redis的代码.py",
}

EXAMPLES_WITHOUT_WORKER = {
    "examples/01_broker_and_config/03_config_patterns.py",
    "examples/07_scheduling/01_redis_schedule_source.py",
    "examples/07_scheduling/02_cron_and_interval.py",
    "examples/10_fastapi_integration/01_fastapi_taskiq.py",
    "examples/10_fastapi_integration/02_fastapi_depends_shared.py",
}

WORKER_ENTRYPOINTS = {
    "examples/09_broker_patterns/01_pubsub_broker.py": ["list_broker"],
    "examples/09_broker_patterns/02_multiple_queues.py": [
        "default_broker",
        "high_priority_broker",
        "batch_broker",
    ],
}

TIMEOUT_OVERRIDES = {
    "examples/05_middlewares/03_retry_middleware.py": 40,
    "examples/06_error_handling/01_reject_and_requeue.py": 40,
    "examples/06_error_handling/02_smart_retry_with_backoff.py": 45,
}

EXAMPLE_TIMEOUT = 30
TEMPLATE_TIMEOUT = 15
WORKER_READY_TIMEOUT = 12
POST_WORKER_STARTUP_WAIT = 2
REDIS_DBS = (0, 1, 2, 3)


@dataclass(slots=True)
class RunSpec:
    """描述 smoke 如何运行单个 Python 文件。"""

    rel_path: str
    module_path: str
    kind: Literal["example", "template"]
    entrypoint: str | None = None
    needs_worker: bool = False
    broker_names: list[str] = field(default_factory=list)
    timeout: int = EXAMPLE_TIMEOUT


def reset_redis() -> None:
    """清空教程专用 Redis DB，避免不同示例互相污染。"""
    for db in REDIS_DBS:
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


def collect_python_files(base: Path) -> list[Path]:
    """收集 examples/ 与 templates/ 下所有 Python 文件。"""
    files: list[Path] = []
    for subdir in ("examples", "templates"):
        root = base / subdir
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return [path for path in sorted(files) if path.name not in SKIP_FILES]


def get_module_path(path: Path, base: Path) -> str:
    """将文件路径转换为可 import 的模块路径。"""
    rel = path.relative_to(base)
    return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")


def build_run_spec(path: Path, base: Path) -> RunSpec:
    """根据路径推导 smoke 运行规格。"""
    rel_path = str(path.relative_to(base)).replace("\\", "/")
    module_path = get_module_path(path, base)
    kind: Literal["example", "template"] = "template" if rel_path.startswith("templates/") else "example"

    if kind == "template":
        return RunSpec(
            rel_path=rel_path,
            module_path=module_path,
            kind=kind,
            entrypoint="_demo",
            needs_worker=False,
            timeout=TEMPLATE_TIMEOUT,
        )

    needs_worker = rel_path not in EXAMPLES_WITHOUT_WORKER
    return RunSpec(
        rel_path=rel_path,
        module_path=module_path,
        kind=kind,
        entrypoint="main",
        needs_worker=needs_worker,
        broker_names=list(WORKER_ENTRYPOINTS.get(rel_path, ["broker"])) if needs_worker else [],
        timeout=TIMEOUT_OVERRIDES.get(rel_path, EXAMPLE_TIMEOUT),
    )


def build_smoke_queue_name(rel_path: str, broker_name: str) -> str:
    """为 smoke 运行生成独立 queue_name，避免不同示例互相抢队列。"""
    normalized = rel_path.removesuffix(".py").replace("/", ":")
    return f"smoke:{normalized}:{broker_name}"


def ensure_wrapper_module(
    module_path: str,
    rel_path: str,
    broker_names: list[str],
    wrapper_dir: Path,
) -> str:
    """生成临时 wrapper module，用于注入独立 queue_name。"""
    wrapper_name = f"_smoke_{sha1(rel_path.encode('utf-8')).hexdigest()[:12]}"
    wrapper_file = wrapper_dir / f"{wrapper_name}.py"

    lines = [
        "from __future__ import annotations",
        "import importlib as _importlib",
        f"_orig = _importlib.import_module({module_path!r})",
    ]
    for broker_name in broker_names:
        queue_name = build_smoke_queue_name(rel_path, broker_name)
        lines.extend(
            [
                f"{broker_name} = getattr(_orig, {broker_name!r})",
                f"if hasattr({broker_name}, 'queue_name'):",
                f"    {broker_name}.queue_name = {queue_name!r}",
                f"setattr(_orig, {broker_name!r}, {broker_name})",
            ]
        )
    lines.extend(
        [
            "main = getattr(_orig, 'main', None)",
            "_demo = getattr(_orig, '_demo', None)",
            "app = getattr(_orig, 'app', None)",
            "scheduler = getattr(_orig, 'scheduler', None)",
        ]
    )
    wrapper_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return wrapper_name


def wait_for_worker_ready(proc: subprocess.Popen[str], timeout: int) -> tuple[bool, str]:
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

            events = selector.select(timeout=0.5)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                lines.append(line.rstrip())
                if "Listening started." in line:
                    return True, "\n".join(lines)
    finally:
        selector.close()

    if proc.poll() is not None and proc.stdout is not None:
        remainder = proc.stdout.read()
        if remainder:
            lines.extend(remainder.splitlines())
    return False, "\n".join(lines)


def start_worker(
    module_path: str,
    broker_name: str,
    base: Path,
    wrapper_dir: Path,
) -> tuple[subprocess.Popen[str] | None, str]:
    """启动 taskiq worker 子进程并等待 ready。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{wrapper_dir}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(wrapper_dir)
    )
    cmd = [
        sys.executable,
        "-m",
        "taskiq",
        "worker",
        f"{module_path}:{broker_name}",
        "--workers",
        "1",
        "--app-dir",
        str(wrapper_dir),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(base),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except Exception as exc:
        return None, str(exc)

    ready, output = wait_for_worker_ready(proc, timeout=WORKER_READY_TIMEOUT)
    if ready:
        return proc, output

    stop_worker(proc)
    if output:
        return None, output
    return None, f"worker 在 {WORKER_READY_TIMEOUT}s 内未就绪"


def stop_worker(proc: subprocess.Popen[str] | None) -> None:
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


def run_entrypoint(
    module_path: str,
    entrypoint: str,
    base: Path,
    timeout: int,
    wrapper_dir: Path | None = None,
) -> tuple[bool, str]:
    """导入模块并运行指定入口函数。"""
    env = os.environ.copy()
    if wrapper_dir is not None:
        env["PYTHONPATH"] = (
            f"{wrapper_dir}{os.pathsep}{env['PYTHONPATH']}"
            if env.get("PYTHONPATH")
            else str(wrapper_dir)
        )

    code = (
        "import asyncio, importlib, inspect\n"
        f"mod = importlib.import_module({module_path!r})\n"
        f"func = getattr(mod, {entrypoint!r}, None)\n"
        "if func is None:\n"
        f"    raise SystemExit({entrypoint!r} + '() not found')\n"
        "result = func()\n"
        "if inspect.isawaitable(result):\n"
        "    asyncio.run(result)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(base),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"超时 ({timeout}s)"
    except Exception as exc:
        return False, str(exc)

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return True, output
    return False, output or f"exit code {completed.returncode}"


def run_python_file(path: Path, base: Path, timeout: int) -> tuple[bool, str]:
    """直接运行 Python 文件。"""
    try:
        completed = subprocess.run(
            [sys.executable, str(path.relative_to(base))],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"超时 ({timeout}s)"
    except Exception as exc:
        return False, str(exc)

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return True, output
    return False, output or f"exit code {completed.returncode}"


def run_one(spec: RunSpec, base: Path, wrapper_dir: Path) -> tuple[str, bool, str]:
    """运行单个文件（含 worker 管理）。"""
    worker_procs: list[subprocess.Popen[str]] = []
    module_for_runner = spec.module_path
    wrapper_dir_for_runner: Path | None = None

    try:
        reset_redis()

        if spec.needs_worker:
            module_for_runner = ensure_wrapper_module(
                module_path=spec.module_path,
                rel_path=spec.rel_path,
                broker_names=spec.broker_names,
                wrapper_dir=wrapper_dir,
            )
            wrapper_dir_for_runner = wrapper_dir

            for broker_name in spec.broker_names:
                worker_proc, worker_output = start_worker(
                    module_path=module_for_runner,
                    broker_name=broker_name,
                    base=base,
                    wrapper_dir=wrapper_dir,
                )
                if worker_proc is None:
                    return (
                        spec.rel_path,
                        False,
                        f"Worker 启动失败: {broker_name}\n{worker_output}",
                    )
                worker_procs.append(worker_proc)
            time.sleep(POST_WORKER_STARTUP_WAIT)

        if spec.entrypoint is not None:
            return spec.rel_path, *run_entrypoint(
                module_path=module_for_runner,
                entrypoint=spec.entrypoint,
                base=base,
                timeout=spec.timeout,
                wrapper_dir=wrapper_dir_for_runner,
            )

        return spec.rel_path, *run_python_file(
            path=base / spec.rel_path,
            base=base,
            timeout=spec.timeout,
        )
    finally:
        for worker_proc in reversed(worker_procs):
            stop_worker(worker_proc)
        try:
            reset_redis()
        except Exception:
            pass


def format_pass_label(spec: RunSpec) -> str:
    """格式化 PASS 行里的 worker 标签。"""
    if not spec.needs_worker:
        return ""

    worker_count = len(spec.broker_names)
    label = "workers" if worker_count != 1 else "worker"
    return f" (w/ {worker_count} {label})"


def main() -> None:
    """运行所有教程文件并打印汇总结果。"""
    base = Path(__file__).resolve().parent.parent
    wrapper_dir = Path(tempfile.mkdtemp(prefix="taskiq_smoke_wrappers_"))

    if not check_redis():
        print("Redis 不可用，请确保 Redis 已启动（密码 123456）", flush=True)
        sys.exit(1)

    print("清理 Redis DB 0/1/2/3...", flush=True)
    reset_redis()

    all_files = collect_python_files(base)
    specs = [build_run_spec(path, base) for path in all_files]
    print(f"找到 {len(specs)} 个 Python 文件\n", flush=True)

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []
    started = time.perf_counter()

    for spec in specs:
        print(f"RUN   {spec.rel_path}", flush=True)
        name, ok, msg = run_one(spec, base, wrapper_dir)

        if msg == "SKIPPED":
            print(f"  SKIP  {name}", flush=True)
            skipped += 1
        elif ok:
            print(f"  PASS  {name}{format_pass_label(spec)}", flush=True)
            passed += 1
        else:
            print(f"  FAIL  {name}", flush=True)
            failed += 1
            failures.append((name, msg))

    elapsed = time.perf_counter() - started
    print(f"\n{'=' * 60}", flush=True)
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过", flush=True)
    print(f"耗时: {elapsed:.1f}s", flush=True)

    if failures:
        print("\n失败详情:", flush=True)
        for name, msg in failures:
            print(f"\n  {name}:", flush=True)
            lines = [line for line in msg.strip().splitlines() if line.strip()]
            for line in lines[-12:]:
                print(f"    {line}", flush=True)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
