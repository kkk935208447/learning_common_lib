"""
Smoke 测试：遍历 examples/ 下所有 .py 文件，逐个运行并收集结果。

目标:
    Smoke 测试：遍历 examples/ 下所有 .py 文件，逐个运行并收集结果。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    见本文件导入、节点函数和构图代码

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: smoke/run_all_examples.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        env LANGGRAPH_STRICT_REDIS=1 uv run python smoke/run_all_examples.py

预期现象:
    运行后可观察本文件对应的状态推进、输出或集成行为

生产提醒:
    迁移到业务代码前，请结合 README / best_practices / pitfalls 一起阅读
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


INTEGRATION_EXAMPLES = {
    "05_checkpointing/04_redis_checkpointer.py",
    "15_production_deployment/01_fastapi_sse_integration.py",
    "16_agentic_rag_patterns/03_celery_bridge.py",
}

REALISTIC_MULTI_AGENT_EXAMPLES = {
    "07_subgraph_composition/05_command_parent_handoff.py",
    "10_multi_agent/06_supervisor_with_subgraphs.py",
    "10_multi_agent/07_replan_with_fingerprint.py",
    "10_multi_agent/08_partial_plan_reuse.py",
}

RESUME_RECOVERY_EXAMPLES = {
    "05_checkpointing/05_checkpoint_schema_evolution.py",
    "05_checkpointing/06_subgraph_thread_strategy.py",
    "05_checkpointing/07_idempotent_resume_side_effects.py",
    "06_streaming/07_store_backed_event_replay.py",
    "08_human_in_the_loop/05_structured_approval_contract.py",
    "08_human_in_the_loop/06_clarify_with_timeout_default.py",
    "09_error_and_resilience/05_retry_policy_and_cache_policy.py",
    "12_memory_and_store/07_store_lifecycle_management.py",
    "14_testing_and_debugging/05_resume_and_replay_tests.py",
    "15_production_deployment/03_double_texting.py",
    "16_agentic_rag_patterns/06_control_plane_vs_runtime_state.py",
    "16_agentic_rag_patterns/07_resume_orchestrator_contract.py",
    "16_agentic_rag_patterns/08_stale_result_fencing.py",
}


def classify_example(rel_path: str) -> str:
    """按教程维度给示例分类。"""
    if rel_path in INTEGRATION_EXAMPLES:
        return "integration"
    if rel_path in REALISTIC_MULTI_AGENT_EXAMPLES:
        return "realistic_multi_agent"
    if rel_path in RESUME_RECOVERY_EXAMPLES:
        return "resume_recovery"
    return "core"


def validate_integration_output(rel_path: str, stdout: str) -> str | None:
    """集成示例必须显式证明自己真的连上了 Redis。"""
    if "RUNTIME_STATUS" not in stdout:
        return "缺少 RUNTIME_STATUS 运行时状态输出"
    if "degraded=True" in stdout:
        return "集成示例发生了 Redis 降级"
    if rel_path == "05_checkpointing/04_redis_checkpointer.py":
        if "RUNTIME_STATUS checkpoint=redis degraded=False" not in stdout:
            return "Redis checkpointer 未确认使用真实 Redis backend"
    if rel_path == "15_production_deployment/01_fastapi_sse_integration.py":
        if "RUNTIME_STATUS checkpoint=redis store=redis degraded=False" not in stdout:
            return "FastAPI SSE 示例未确认 checkpoint/store 都使用真实 Redis backend"
    if rel_path == "16_agentic_rag_patterns/03_celery_bridge.py":
        if "RUNTIME_STATUS checkpoint=redis degraded=False" not in stdout:
            return "Celery bridge 示例未确认使用真实 Redis checkpoint backend"
    return None


def run_all() -> dict[str, list]:
    """运行所有示例文件，返回结果汇总。"""
    tutorial_root = Path(__file__).resolve().parent.parent
    project_root = tutorial_root.parents[3]
    examples_dir = tutorial_root / "examples"
    results: dict[str, list] = {"passed": [], "failed": [], "skipped": []}
    kind_summary = {
        "core": {"passed": 0, "failed": 0, "skipped": 0},
        "integration": {"passed": 0, "failed": 0, "skipped": 0},
        "realistic_multi_agent": {"passed": 0, "failed": 0, "skipped": 0},
        "resume_recovery": {"passed": 0, "failed": 0, "skipped": 0},
    }

    if not examples_dir.exists():
        print(f"示例目录不存在: {examples_dir}")
        return results

    py_files = sorted(
        py_file
        for py_file in examples_dir.rglob("*.py")
        if py_file.name != "__init__.py"
    )
    if not py_files:
        print("未找到任何 .py 文件")
        return results

    print(f"共发现 {len(py_files)} 个示例文件\n")

    runner = "import runpy, sys; runpy.run_path(sys.argv[1], run_name='__main__')"
    env = os.environ.copy()
    pythonpath_parts = [str(project_root / "src")]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env["LANGGRAPH_STRICT_REDIS"] = "1"

    for py_file in py_files:
        rel_path = str(py_file.relative_to(examples_dir))
        kind = classify_example(rel_path)
        print(f"{'=' * 60}")
        print(f"运行: [{kind}] {rel_path}")

        try:
            result = subprocess.run(
                [sys.executable, "-c", runner, str(py_file)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=project_root,
                env=env,
            )
            validation_error = None
            if result.returncode == 0 and kind == "integration":
                validation_error = validate_integration_output(rel_path, result.stdout)

            if result.returncode == 0 and validation_error is None:
                results["passed"].append(rel_path)
                kind_summary[kind]["passed"] += 1
                print(f"  [PASS] 通过")
            else:
                error_text = validation_error or result.stderr[:400] or result.stdout[:400]
                results["failed"].append((rel_path, error_text))
                kind_summary[kind]["failed"] += 1
                print(f"  [FAIL] 失败: {error_text[:200]}")
        except subprocess.TimeoutExpired:
            results["skipped"].append(rel_path)
            kind_summary[kind]["skipped"] += 1
            print(f"  [SKIP] 超时跳过")
        except Exception as exc:
            results["failed"].append((rel_path, str(exc)[:200]))
            kind_summary[kind]["failed"] += 1
            print(f"  [FAIL] 异常: {exc}")

    # 汇总
    print(f"\n{'=' * 60}")
    total = len(results["passed"]) + len(results["failed"]) + len(results["skipped"])
    print(f"总计: {total}")
    print(f"通过: {len(results['passed'])}")
    print(f"失败: {len(results['failed'])}")
    print(f"跳过: {len(results['skipped'])}")

    print("\n分类汇总:")
    for kind, summary in kind_summary.items():
        print(
            f"  {kind}: pass={summary['passed']} "
            f"fail={summary['failed']} skip={summary['skipped']}"
        )

    if results["failed"]:
        print("\n失败详情:")
        for name, err in results["failed"]:
            print(f"  - {name}: {err[:100]}")

    return results


if __name__ == "__main__":
    run_all()
