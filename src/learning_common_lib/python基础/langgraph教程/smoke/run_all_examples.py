"""Smoke 测试：遍历 examples/ 下所有 .py 文件，逐个运行并收集结果。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


INTEGRATION_EXAMPLES = {
    "05_checkpointing/04_redis_checkpointer.py",
    "15_production_deployment/01_fastapi_sse_integration.py",
    "16_agentic_rag_patterns/03_celery_bridge.py",
}


def classify_example(rel_path: str) -> str:
    """按教程维度给示例分类。"""
    return "integration" if rel_path in INTEGRATION_EXAMPLES else "core"


def run_all() -> dict[str, list]:
    """运行所有示例文件，返回结果汇总。"""
    examples_dir = Path(__file__).parent.parent / "examples"
    results: dict[str, list] = {"passed": [], "failed": [], "skipped": []}
    kind_summary = {
        "core": {"passed": 0, "failed": 0, "skipped": 0},
        "integration": {"passed": 0, "failed": 0, "skipped": 0},
    }

    if not examples_dir.exists():
        print(f"示例目录不存在: {examples_dir}")
        return results

    py_files = sorted(examples_dir.rglob("*.py"))
    if not py_files:
        print("未找到任何 .py 文件")
        return results

    print(f"共发现 {len(py_files)} 个示例文件\n")

    for py_file in py_files:
        rel_path = str(py_file.relative_to(examples_dir))
        kind = classify_example(rel_path)
        print(f"{'=' * 60}")
        print(f"运行: [{kind}] {rel_path}")

        try:
            result = subprocess.run(
                [sys.executable, str(py_file)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                results["passed"].append(rel_path)
                kind_summary[kind]["passed"] += 1
                print(f"  [PASS] 通过")
            else:
                results["failed"].append((rel_path, result.stderr[:200]))
                kind_summary[kind]["failed"] += 1
                print(f"  [FAIL] 失败: {result.stderr[:200]}")
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
