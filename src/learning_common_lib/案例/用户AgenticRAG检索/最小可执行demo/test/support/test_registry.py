"""Canonical registry for setup scripts and test suites.

README、run_all.py、production_stack_suite.py 应优先引用这里的清单，
避免测试入口顺序和说明多处维护后发生漂移。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScriptSpec:
    relative_path: str
    description: str


@dataclass(frozen=True, slots=True)
class SuiteCaseSpec:
    key: str
    runner_name: str
    description: str
    needs_base_url: bool = False


PREPARE_DEMO_ENV_SCRIPT = ScriptSpec(
    relative_path="scripts/setup/prepare_demo_env.py",
    description="重建上游活动知识并重置当前 DeepSearch 控制面",
)


OFFLINE_SCRIPT_SPECS = (
    ScriptSpec("test/offline/test_offline_happy_path.py", "标准离线提交、规划、分发、汇总闭环"),
    ScriptSpec("test/offline/test_preplan_clarify.py", "PREPLAN Clarify 请求、回复、恢复"),
    ScriptSpec("test/offline/test_step_gate_clarify.py", "STEP_GATE Clarify 与用户口径选择"),
    ScriptSpec("test/offline/test_subtask_retry.py", "首次检索证据不足，补检后完成"),
    ScriptSpec("test/offline/test_replan_flow.py", "首次执行失败后进入真实 Replan 并收敛"),
    ScriptSpec("test/offline/test_replan_reuse.py", "重规划生成新 DAG 并复用已完成子任务"),
    ScriptSpec("test/offline/test_stale_result_fencing.py", "旧执行结果只写 STALE_IGNORED，不推进新计划"),
    ScriptSpec("test/offline/test_dispatch_gap_recovery.py", "CLAIMED/DISPATCHED 缺口由 maintenance 补发"),
    ScriptSpec("test/offline/test_runtime_cache_rebuild.py", "Redis 热缓存可按 MySQL 重建"),
    ScriptSpec("test/offline/test_checkpoint_degraded_recovery.py", "checkpoint Redis 不可用时降级到 memory backend"),
    ScriptSpec("test/offline/test_checkpoint_resume_recovery.py", "maintenance 优先从 checkpoint next 节点恢复"),
    ScriptSpec("test/offline/test_fallback_partial_result.py", "降级输出仍保留部分结果、引用和不确定性说明"),
    ScriptSpec("test/offline/test_invalid_citation_filter.py", "最终引用会过滤掉无效 citation"),
)


SERVICE_SUITE_CASE_SPECS = (
    SuiteCaseSpec("http_completion", "test_http_completion", "HTTP 提交到完成态", needs_base_url=True),
    SuiteCaseSpec("sse_sequence", "test_sse_sequence", "SSE 事件序列与回放", needs_base_url=True),
    SuiteCaseSpec("sse_invalid_last_event_id", "test_sse_invalid_last_event_id", "非法 Last-Event-ID 返回 400", needs_base_url=True),
    SuiteCaseSpec("clarify_flow", "test_clarify_flow", "PREPLAN Clarify HTTP 契约", needs_base_url=True),
    SuiteCaseSpec("duplicate_clarification", "test_duplicate_clarification_submission_returns_snapshot", "重复 Clarify 提交返回快照", needs_base_url=True),
    SuiteCaseSpec("expired_clarify_defaults", "test_expired_clarify_defaults", "Clarify 超时默认项应用", needs_base_url=True),
    SuiteCaseSpec("time_serialization_uses_utc", "test_time_serialization_uses_utc", "HTTP/SSE 时间统一使用 UTC", needs_base_url=True),
    SuiteCaseSpec("sse_clarification_payload", "test_sse_clarification_payload_and_heartbeat", "Clarify SSE payload 与 heartbeat", needs_base_url=True),
    SuiteCaseSpec("invalid_scope_validation", "test_invalid_scope_validation", "非法 scope_json 返回 422", needs_base_url=True),
    SuiteCaseSpec("step_gate_clarify_flow", "test_step_gate_clarify_flow", "STEP_GATE Clarify HTTP 契约", needs_base_url=True),
)


PRODUCTION_OFFLINE_CASE_SPECS = (
    SuiteCaseSpec("offline_submit", "test_offline_submit", "离线提交到完成态"),
    SuiteCaseSpec("duplicate_execution_id", "test_duplicate_execution_id_is_ignored", "重复 execution_id 不重复执行"),
    SuiteCaseSpec("stale_result_resume", "test_stale_result_does_not_advance_new_plan", "旧执行结果不推进新计划"),
    SuiteCaseSpec("replan_reuse", "test_replan_creates_distinct_plan_and_reuses_completed_subtasks", "重规划复用已完成子任务"),
    SuiteCaseSpec("fallback_late_result_guard", "test_fallback_ignores_late_result_and_staged_payload", "终态后忽略晚到结果与 staged payload"),
    SuiteCaseSpec("maintenance_recovery", "test_maintenance_recovery_resumes_terminal_plan", "maintenance 恢复 terminal plan"),
    SuiteCaseSpec("maintenance_recovery_planning_finalizing", "test_maintenance_recovery_resumes_planning_and_finalizing", "maintenance 恢复 planning/finalizing"),
    SuiteCaseSpec("maintenance_recovery_ready_tasks", "test_maintenance_recovery_resumes_ready_tasks", "maintenance 恢复 READY 任务"),
    SuiteCaseSpec("reaped_run_payload_guard", "test_reaped_run_payload_is_rejected", "被收割 run 的 payload 刷库被拒绝"),
    SuiteCaseSpec("checkpoint_resume_recovery", "test_checkpoint_resume_recovery", "checkpoint next 节点恢复"),
    SuiteCaseSpec("redis_memory_layers", "test_redis_memory_layers", "L2/L3/快照/事件缓存存在"),
    SuiteCaseSpec("dag_fingerprint_semantics", "test_dag_fingerprint_distinguishes_semantics", "语义不同的 DAG 指纹不同"),
    SuiteCaseSpec("invalid_citation_filtering", "test_final_answer_filters_invalid_citations", "非法 citation 被过滤"),
    SuiteCaseSpec("fallback_partial_results", "test_fallback_returns_partial_results", "降级输出保留部分结果"),
    SuiteCaseSpec("finalize_degraded_guidance", "test_finalize_degraded_includes_guidance", "Finalize 降级包含下一步建议"),
    SuiteCaseSpec("checkpoint_env_isolation", "test_checkpoint_does_not_mutate_redis_url_env", "checkpoint 不污染 REDIS_URL"),
)
