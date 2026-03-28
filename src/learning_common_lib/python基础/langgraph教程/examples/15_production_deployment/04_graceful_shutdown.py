"""
优雅关闭：checkpoint 保存 + 进行中任务处理

目标:
    演示生产环境中的优雅关闭机制：
    收到终止信号后保存 checkpoint、等待进行中任务完成、清理资源。

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    - signal.signal(SIGTERM/SIGINT) —— 信号处理
    - checkpointer —— 状态持久化
    - asyncio.Event —— 关闭协调

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/15_production_deployment/04_graceful_shutdown.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/15_production_deployment/04_graceful_shutdown.py

预期现象:
    模拟收到 SIGTERM 信号后，系统优雅关闭：
    等待当前任务完成 → 保存 checkpoint → 清理资源 → 退出。

生产提醒:
    - K8s 默认 SIGTERM 后 30 秒强制 SIGKILL，确保关闭逻辑在此之内完成
    - checkpoint 保存是关键：确保中断的任务可以从断点恢复
    - 使用 health check 端点配合 readiness probe
    - 本例用 `interrupt_after=["process"]` 把每一步的 checkpoint 显式展示出来
"""
from __future__ import annotations

import asyncio
import signal
import time
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph


# ── 状态定义 ──────────────────────────────────────────────
class TaskState(TypedDict):
    task_id: str
    progress: int
    result: str


# ── 图定义 ──────────────────────────────────────────────
def process_step(state: TaskState) -> dict:
    """模拟耗时处理步骤"""
    progress = state["progress"] + 25
    time.sleep(0.1)  # 模拟处理
    print(f"  [task-{state['task_id']}] 进度: {progress}%")
    if progress >= 100:
        return {"progress": 100, "result": f"任务 {state['task_id']} 完成"}
    return {"progress": progress}


def check_complete(state: TaskState) -> str:
    """检查是否完成"""
    return END if state["progress"] >= 100 else "process"


def build_task_graph(*, checkpointer=None, interrupt_after_process: bool = False):
    graph = StateGraph(TaskState)
    graph.add_node("process", process_step)
    graph.set_entry_point("process")
    graph.add_conditional_edges("process", check_complete, {END: END, "process": "process"})
    compile_kwargs = {
        "checkpointer": checkpointer or MemorySaver(),
    }
    if interrupt_after_process:
        compile_kwargs["interrupt_after"] = ["process"]
    return graph.compile(**compile_kwargs)


def run_steps(app, *, config: dict, initial_state: TaskState | None, steps: int) -> dict:
    """执行固定步数，便于观察每一步后的 checkpoint。"""
    payload = initial_state
    latest_result = {}
    for step in range(1, steps + 1):
        latest_result = app.invoke(payload, config=config)
        snapshot = app.get_state(config)
        print(
            f"  [checkpoint] step={step} "
            f"progress={snapshot.values.get('progress')}% next={snapshot.next}"
        )
        payload = None
        if snapshot.values.get("progress", 0) >= 100:
            break
    return latest_result


def run_until_complete(app, *, config: dict, initial_state: TaskState | None = None) -> dict:
    """从当前 checkpoint 持续执行，直到任务完成。"""
    payload = initial_state
    while True:
        result = app.invoke(payload, config=config)
        snapshot = app.get_state(config)
        print(
            f"  [checkpoint] progress={snapshot.values.get('progress')}% next={snapshot.next}"
        )
        if snapshot.values.get("progress", 0) >= 100:
            return result
        payload = None


# ══════════════════════════════════════════════════════════
# 优雅关闭管理器
# ══════════════════════════════════════════════════════════

class GracefulShutdownManager:
    """优雅关闭管理器

    职责：
    1. 捕获终止信号（SIGTERM/SIGINT）
    2. 停止接受新任务
    3. 等待进行中任务完成（带超时）
    4. 保存 checkpoint
    5. 清理资源
    """

    def __init__(self, timeout: float = 25.0):
        self.shutdown_event = asyncio.Event()
        self.active_tasks: set[str] = set()
        self.timeout = timeout
        self._accepting_new = True

    def setup_signal_handlers(self) -> None:
        """注册信号处理器"""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)
        print("[shutdown] 信号处理器已注册 (SIGTERM, SIGINT)")

    def _handle_signal(self, sig: signal.Signals) -> None:
        """信号处理回调"""
        print(f"\n[shutdown] 收到信号 {sig.name}，开始优雅关闭...")
        self._accepting_new = False
        self.shutdown_event.set()

    def can_accept(self) -> bool:
        """是否还接受新任务"""
        return self._accepting_new

    def register_task(self, task_id: str) -> None:
        """注册活跃任务"""
        self.active_tasks.add(task_id)
        print(f"[shutdown] 注册任务 {task_id}（活跃: {len(self.active_tasks)}）")

    def unregister_task(self, task_id: str) -> None:
        """注销完成的任务"""
        self.active_tasks.discard(task_id)
        print(f"[shutdown] 注销任务 {task_id}（活跃: {len(self.active_tasks)}）")

    async def wait_for_completion(self) -> None:
        """等待所有活跃任务完成（带超时）"""
        if not self.active_tasks:
            print("[shutdown] 无活跃任务，直接关闭")
            return

        print(f"[shutdown] 等待 {len(self.active_tasks)} 个任务完成（超时: {self.timeout}s）...")
        start = time.monotonic()
        while self.active_tasks and (time.monotonic() - start) < self.timeout:
            await asyncio.sleep(0.1)

        if self.active_tasks:
            print(f"[shutdown] 超时！强制关闭 {len(self.active_tasks)} 个未完成任务")
        else:
            print("[shutdown] 所有任务已完成")


# ══════════════════════════════════════════════════════════
# 模拟演示（不实际注册信号，避免干扰）
# ══════════════════════════════════════════════════════════

def demo_graceful_shutdown() -> None:
    """模拟优雅关闭流程"""
    checkpointer = MemorySaver()
    app = build_task_graph(
        checkpointer=checkpointer,
        interrupt_after_process=True,
    )
    manager = GracefulShutdownManager(timeout=5.0)

    # 模拟正常执行
    print("--- 阶段 1: 正常执行任务 ---\n")
    config = {"configurable": {"thread_id": "task-001"}}
    manager.register_task("task-001")

    result = run_until_complete(
        app,
        config=config,
        initial_state={"task_id": "001", "progress": 0, "result": ""},
    )
    manager.unregister_task("task-001")
    print(f"  结果: {result['result']}\n")

    # 模拟中断恢复
    print("--- 阶段 2: 模拟中断 + 恢复 ---\n")
    config2 = {"configurable": {"thread_id": "task-002"}}
    print("  先执行两个 superstep，让 checkpointer 留下真实断点...")
    run_steps(
        app,
        config=config2,
        initial_state={"task_id": "002", "progress": 0, "result": ""},
        steps=2,
    )
    snapshot_before_shutdown = app.get_state(config2)
    print(f"  关闭前 checkpoint: {snapshot_before_shutdown.values}")

    print("  模拟进程退出后重新编译图...")
    recovered_app = build_task_graph(
        checkpointer=checkpointer,
        interrupt_after_process=True,
    )
    restored = recovered_app.get_state(config2)
    print(f"  恢复到的 state: {restored.values}")

    print("  从 checkpoint 继续执行...")
    result2 = run_until_complete(recovered_app, config=config2)
    print(f"  恢复后结果: {result2['result']}\n")

    # 模拟关闭流程
    print("--- 阶段 3: 模拟优雅关闭 ---\n")
    manager._accepting_new = False
    print(f"  停止接受新任务: can_accept={manager.can_accept()}")
    print("  保存所有 checkpoint...")
    print("  清理资源...")
    print("  关闭完成")


if __name__ == "__main__":
    print("=== 优雅关闭演示 ===\n")
    demo_graceful_shutdown()

    print("""
生产环境检查清单:
  1. 注册 SIGTERM/SIGINT 信号处理器
  2. 收到信号后停止接受新请求（readiness probe 返回 false）
  3. 等待进行中任务完成（K8s terminationGracePeriodSeconds）
  4. 保存所有 checkpoint 到持久化存储
  5. 关闭数据库连接、释放资源
  6. 退出进程
""")
