from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

try:
    from ..support.bootstrap import print_result, setup_test_env
except ImportError:
    from support.bootstrap import print_result, setup_test_env

setup_test_env()
os.environ["DEEPSEARCH_DEMO_REDIS_PASSWORD"] = "wrong-password-for-checkpoint-test"

try:
    from ...infrastructure.runtime_bundle import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )
except ImportError:
    from 最小可执行demo.infrastructure.runtime_bundle import (
        build_global_graph_service_from_bundle,
        build_runtime_bundle,
        close_runtime_bundle,
    )


async def main() -> dict:
    runtime = build_runtime_bundle(use_task_engine=True)
    try:
        await build_global_graph_service_from_bundle(runtime, use_task_engine=True)
        adapter = getattr(runtime, "checkpoint_adapter", None)
        if adapter is None:
            raise AssertionError("checkpoint adapter was not created")
        if not adapter.degraded or adapter.backend != "memory":
            raise AssertionError(
                f"checkpoint should degrade to memory when Redis auth fails, got backend={adapter.backend} degraded={adapter.degraded}"
            )
        return {"backend": adapter.backend, "degraded": adapter.degraded, "last_error": adapter.last_error}
    finally:
        await close_runtime_bundle(runtime)


if __name__ == "__main__":
    print_result(asyncio.run(main()))
