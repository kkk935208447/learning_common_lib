# Agentic RAG 用户深度检索 架构设计规划（Codex 修订版）

## 1. 文档目的

本规划用于指导 `src/learning_common_lib/案例/用户AgenticRAG检索` 目录下后续代码实现，目标是搭建一套企业生产级的 Multi-Agent Deep Search 系统骨架，采用 Plan-Execute-Replan 双循环架构。

本次规划优先解决以下问题：

1. 全局规划层（Planner → DAG → Scheduler → StepGate）如何做状态管理与并发调度。
2. 子任务执行闭环（路由 → 改写 → 多路检索 → 证据评估 → 纠偏）如何做可控迭代。
3. 五层记忆系统（L1~L5）如何分层存储与跨 Agent 共享。
4. 高并发场景下的锁策略、幂等性、超时熔断如何设计。
5. 如何复用当前仓库已有的 SQLAlchemy、Redis/Celery、统一异常处理经验。

配套细化说明见 [codex_技术拆解](./codex_技术拆解.md)，覆盖以下关键技术点：

1. [LangGraph DAG 编排](./codex_技术拆解.md#langgraph-dag)：编排引擎选型、两图架构、State Schema、条件边、并行执行、Checkpointing、与 Celery 分工。
2. [任务状态传递与 Redis 存储](./codex_技术拆解.md#state-redis)：Key 命名规范、全局任务状态、DAG 入度表 Lua 脚本、子任务工作记忆、证据池、预算追踪、事件流、Scheduler 就绪发现。
3. [Celery 高并发适配](./codex_技术拆解.md#celery-concurrency)：定位、首版够用的理由、真实瓶颈、缓解措施、演进路径。
4. [全局循环与子任务循环的交互边界](./codex_技术拆解.md#loop-boundary)：职责划分、升级协议、证据共享、Replan 取消策略。
5. [证据冲突仲裁](./codex_技术拆解.md#conflict-arbitration)：检测时机、仲裁策略、不可调和冲突处理。
6. [Replan 循环检测与收敛保证](./codex_技术拆解.md#replan-convergence)：DAG 指纹、相似度检测、收敛策略、最终兜底。

> 本文在保留原始蓝图细化流程图、模块拆解、算法说明和示例密度的前提下，只修正会导致实现偏差的存储、一致性、编排和首版范围问题。首版关系型真理源统一为 MySQL。

## 2. 总体结论

推荐采用以下总体方案：

1. **双循环解耦**。全局循环（Global Loop）负责任务分解、DAG 调度、步骤推进判定、全局重规划；子任务循环（Local Loop）负责检索-评估-纠偏，两层独立迭代互不干扰。
2. **MySQL 作为任务状态真理源**。所有 DAG 状态、子任务状态、证据评估结果、预算消耗全部落 MySQL，Redis 仅做热缓存和协调锁。
3. **Redis 作为热缓存与协调层**。Redis 负责 LangGraph checkpoint、入度/预算热数据、工作记忆和短 TTL 锁，不作为首版唯一调度总线；真正的调度推进以 LangGraph 编排状态和 MySQL 真理源为准。
4. **Celery 作为异步执行引擎**。子任务的检索、LLM 调用、证据评估等 CPU/IO 密集操作由 Celery Worker 执行；Worker 完成后回写结果并触发恢复编排，而不是直接链式调度下游。
5. **Blackboard 模式做跨 Agent 协调**。所有 Agent 通过读写 L3（任务级状态记忆）来共享证据和状态，而不是直接互传上下文，避免 3-10x token 浪费。
6. **证据卡（Evidence Card）作为统一数据契约**。从多路检索到评估、生成、校验，全链路以结构化证据卡为数据单元。
7. **Port + Adapter 架构抽象外部依赖**。LLM Provider、向量库、ES、图数据库、Web 搜索均通过 Port 接口抽象，首版提供 Mock 实现。
8. **多层超时 + 轻量熔断**。单次 LLM 调用、单路检索、子任务、全局任务分别设置超时，对外部服务维护熔断状态。
9. **全链路可追踪**。request_id → plan_id → subtask_id → retrieval_call_id 四级追踪，关键节点埋点。

## 3. 核心架构概览

### 图1：全局循环（Plan-Execute-Replan）

```mermaid
flowchart TB
    subgraph EntryLayer["入口层"]
        API["HTTP API / 轮询查询<br/>可选 WebSocket"]
        Auth{"身份/租户/ACL 校验"}
        Denied["拒绝 + 告警"]
    end

    subgraph ControlPlane["控制平面（跨层）"]
        Ctrl["统一控制器<br/>Policy + Budget + StopRule"]
    end

    subgraph GlobalLoop["全局循环 - LangGraph GlobalGraph"]
        Intake["任务画像<br/>intent/complexity/risk/sla"]
        Planner["分层规划器"]
        DAG["DAG 生成<br/>+ 指纹哈希"]
        Scheduler["子任务调度器<br/>拓扑排序 + Send() 分发执行请求"]
        Executor["executor 节点<br/>登记 execution_id + 分发 Celery"]
        StepGate{"主步骤推进判定"}
        GlobalReplan["全局重规划"]
        LoopGuard{"迭代守卫<br/>max_iter / 指纹循环 / 边际收益"}
        Fallback["安全降级输出<br/>不确定性 + 下一步建议"]
        Output["最终回答<br/>引用 + 置信度"]
    end

    API --> Auth
    Auth -- "拒绝" --> Denied
    Auth -- "通过" --> Intake
    Intake --> Planner --> DAG --> Scheduler
    Scheduler -- "Send() 并行" --> Executor
    Executor --> StepGate
    StepGate -- "执行下一步" --> Scheduler
    StepGate -- "修改原计划" --> GlobalReplan
    StepGate -- "全部完成" --> Output
    GlobalReplan --> LoopGuard
    LoopGuard -- "允许" --> Planner
    LoopGuard -- "超限" --> Fallback --> Output

    Ctrl -. "策略约束" .-> Planner
    Ctrl -. "预算约束" .-> Executor
    Ctrl -. "停止约束" .-> LoopGuard
```

> **说明**：图中 `Executor → StepGate` 表示子任务执行完成后通过 `resume_orchestrator` 恢复 `GlobalGraph` 再进入 `step_gate`，不表示在 LangGraph 节点内同步阻塞等待 Celery `.get()`。

### 图2：子任务闭环（SubtaskGraph）

```mermaid
flowchart TD
    Router{"路由决策<br/>并行/串行/工具选择"}
    CacheProbe{"语义缓存探测"}
    FreshnessCheck{"缓存时效校验<br/>TTL / 数据新鲜度"}
    RewriteRoute{"改写路由<br/>按 route_hint 激活"}

    subgraph RewriteLayer["查询改写层"]
        QV["语义增强改写"]
        QK["精准术语提取"]
        QS["结构化翻译"]
        QG["图查询规划"]
        QW["外部检索准备"]
    end

    Retrieval["多路并发检索"]
    Merge["证据汇聚 + 去重"]
    Fusion["RRF 排序融合"]
    Rerank["轻量重排 → 深度重排"]
    Compress["证据压缩与原子化"]
    EvalScore["三维评估打分<br/>Coverage / Conflict / Confidence"]
    Threshold{"阈值判定"}
    ParentHydration["父文档按需召回"]
    DraftClaims["生成候选答案"]
    Verify{"三重校验"}
    CacheWrite["缓存回写"]
    Done["子任务完成"]

    RetryFactual["重新生成<br/>事实不一致"]
    RetrySensitive["脱敏处理<br/>敏感信息"]
    RetryCitation["重新标注<br/>引用不对齐"]

    GapDiag["缺口诊断"]
    GapMap["缺口→纠偏动作映射"]
    Clarify["追问关键缺失信息"]
    LocalGuard{"子任务迭代守卫"}
    Escalate["升级到全局重规划<br/>含升级报告"]

    Router --> CacheProbe
    CacheProbe -- "命中" --> FreshnessCheck
    FreshnessCheck -- "新鲜" --> EvalScore
    FreshnessCheck -- "过期" --> RewriteRoute
    CacheProbe -- "未命中" --> RewriteRoute

    RewriteRoute --> QV & QK & QS & QG & QW
    QV & QK & QS & QG & QW --> Retrieval
    Retrieval --> Merge --> Fusion --> Rerank --> Compress --> EvalScore
    EvalScore --> Threshold

    Threshold -- "充分" --> ParentHydration --> DraftClaims --> Verify
    Verify -- "通过" --> CacheWrite --> Done
    Verify -- "事实不一致" --> RetryFactual --> LocalGuard
    Verify -- "敏感信息" --> RetrySensitive --> LocalGuard
    Verify -- "引用不对齐" --> RetryCitation --> LocalGuard

    Threshold -- "不充分" --> GapDiag
    GapDiag -- "可补检" --> GapMap --> LocalGuard
    GapDiag -- "需用户补充" --> Clarify

    LocalGuard -- "允许" --> Router
    LocalGuard -- "超限" --> Escalate
```

### 图3：记忆系统数据流

```mermaid
flowchart LR
    subgraph Agents["Agent 节点"]
        Planner["Planner"]
        Executor["Executor"]
        Evaluator["Evaluator"]
        Verifier["Verifier"]
    end

    subgraph Memory["记忆层级"]
        L1["L1 上下文窗口<br/>单次 LLM 调用"]
        L2["L2 工作记忆<br/>子任务级"]
        L3["L3 任务状态<br/>Blackboard"]
        L4["L4 会话记忆<br/>跨轮次"]
        L5["L5 长期记忆<br/>跨会话"]
    end

    subgraph Storage["存储"]
        Redis["Redis"]
        MySQL["MySQL"]
        VecDB["向量库"]
    end

    Planner -- "读 L3 证据池" --> L3
    Planner -- "写 DAG" --> L3
    Executor -- "读/写 L2" --> L2
    Executor -- "写证据卡到 L3" --> L3
    Evaluator -- "读 L2 + L3" --> L2
    Evaluator -- "读 L2 + L3" --> L3
    Verifier -- "读 L2" --> L2

    L1 -- "组装自" --> L2
    L1 -- "组装自" --> L3
    L1 -- "组装自" --> L4
    L2 -- "checkpoint" --> Redis
    L3 -- "双写" --> Redis
    L3 -- "持久化" --> MySQL
    L4 -- "摘要存储" --> MySQL
    L5 -- "用户画像" --> MySQL
    L5 -- "语义缓存" --> VecDB
```

> **说明**：L5 继续保留为长期记忆层，但首版只要求接口和数据契约预留，不要求与主调度链路同步落地。

## 4. 推荐的领域模型

### 4.1 实体拆分

建议拆成以下核心实体：

1. **检索任务** `search_tasks` — 用户发起的一次完整检索请求
2. **执行计划** `task_plans` — Planner 生成的 DAG 计划（支持版本化）
3. **子任务** `subtasks` — DAG 中的每个节点
4. **子任务依赖** `subtask_dependencies` — DAG 边（依赖关系+依赖类型）
5. **证据卡** `evidence_cards` — 原子化证据，跨子任务共享
6. **证据评估记录** `evidence_evaluations` — 每轮评估的三维打分
7. **子任务输出** `subtask_outputs` — 子任务的候选答案与校验结果
8. **会话记录** `sessions` — 会话级情景记忆
9. **会话轮次** `session_turns` — 每轮对话摘要
10. **用户偏好** `user_preferences` — 跨会话长期记忆
11. **语义缓存** `semantic_cache` — 查询级缓存（向量库侧）
12. **预算消耗记录** `budget_ledger` — 细粒度预算追踪

### 4.2 设计原则

1. `search_tasks` 是一次用户请求的生命周期载体，承载全局预算和控制信号。
2. `task_plans` 支持版本化，每次 GlobalReplan 生成新版本，旧版本保留用于循环检测。
3. `subtasks` 归属于某个 plan 版本，状态机独立于全局任务。
4. `evidence_cards` 以 `card_uid` 为全局唯一标识，跨子任务共享，避免重复检索。
5. 子任务之间通过 L3（`search_tasks` + `evidence_cards`）间接通信，不直接传递上下文。

> **首版边界说明**：`user_preferences`、`semantic_cache`、`budget_ledger` 允许先保留接口与最小数据契约，不要求与核心 DAG 调度链路同时落表；`search_tasks`、`task_plans`、`subtasks`、`subtask_dependencies`、`evidence_cards`、`evidence_evaluations`、`subtask_outputs`、`sessions`、`session_turns` 仍是首版主干实体。

## 5. 表设计建议

### 5.1 `search_tasks`

用途：用户发起的一次完整检索任务，是全局生命周期载体。

关键字段建议：

- `id` bigint pk
- `request_id` varchar(64) unique — 全链路追踪 ID
- `session_id` varchar(64) not null
- `tenant_id` varchar(64) not null
- `user_id` varchar(64) not null
- `original_query` text not null
- `resolved_query` text — 指代消解后的完整查询
- `task_profile_json` json — 任务画像（intent/complexity/risk/sla）
- `status` enum(`PENDING`, `PLANNING`, `EXECUTING`, `COMPLETED`, `FAILED`, `DEGRADED`) not null
- `active_plan_version` int not null default 0
- `budget_json` json not null — 预算配置与消耗快照
- `control_json` json — 控制信号（policy/threshold_profile/stop_reason）
- `final_answer` text — 最终回答
- `final_confidence` decimal(4,3) — 最终置信度
- `final_citations_json` json — 引用列表
- `replan_count` int not null default 0
- `total_llm_tokens` int not null default 0
- `total_retrieval_calls` int not null default 0
- `elapsed_ms` int not null default 0
- `created_at` datetime not null
- `updated_at` datetime not null
- `completed_at` datetime

索引建议：

- `index(session_id)`
- `index(tenant_id, user_id, status)`
- `index(status, created_at)`

### 5.2 `task_plans`

用途：Planner 生成的 DAG 计划，支持版本化以实现 Replan 追踪。

关键字段建议：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `dag_json` json not null — 完整 DAG 结构快照
- `dag_fingerprint` char(64) not null — DAG 指纹哈希，用于循环检测
- `replan_reason` varchar(512) — 触发重规划的原因
- `created_at` datetime not null

唯一约束建议：

- `unique(task_id, plan_version)`
- `index(tenant_id, task_id, plan_version)`

### 5.3 `subtasks`

用途：DAG 中的每个执行节点。

关键字段建议：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `subtask_code` varchar(32) not null — 如 ST-001
- `description` text not null
- `task_type` enum(`RETRIEVAL`, `REASONING`, `REFLECTION`) not null
- `route_hint_json` json — Planner 建议的检索路由
- `priority` int not null default 1
- `status` enum(`PENDING`, `READY`, `RUNNING`, `COMPLETED`, `FAILED`, `SKIPPED`) not null
- `iteration` int not null default 0
- `max_iterations` int not null default 3
- `timeout_ms` int not null default 30000
- `final_score` decimal(4,3) — 最终证据评估总分
- `key_findings` text — 压缩摘要
- `evidence_refs_json` json — 引用的证据卡 ID 列表
- `budget_consumed_json` json — 本子任务消耗
- `last_error_code` varchar(64)
- `last_error_message` varchar(1024)
- `current_execution_id` varchar(96) — 当前活跃执行实例 ID，用于回写 fencing
- `worker_id` varchar(128)
- `row_version` bigint not null default 0
- `created_at` datetime not null
- `updated_at` datetime not null
- `started_at` datetime
- `completed_at` datetime

唯一约束建议：

- `unique(task_id, plan_version, subtask_code)`
- `index(tenant_id, task_id, plan_version, status)`
- `index(status, priority)`

`current_execution_id` 必须在 `READY → RUNNING` 的条件更新时一并写入；后续 Worker 回写结果时，必须同时校验 `tenant_id + task_id + plan_version + subtask_code + current_execution_id`，防止旧执行结果污染新计划。

### 5.4 `subtask_dependencies`

用途：DAG 边，表达子任务间的依赖关系与依赖类型。

关键字段建议：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `subtask_code` varchar(32) not null — 当前子任务
- `depends_on_code` varchar(32) not null — 依赖的子任务
- `dependency_type` enum(`HARD`, `SOFT`) not null default `HARD`
- `fallback_strategy` varchar(64) — SOFT 依赖失败时的降级策略

唯一约束建议：

- `unique(task_id, plan_version, subtask_code, depends_on_code)`
- `index(tenant_id, task_id, plan_version, subtask_code)`

### 5.5 `evidence_cards`

用途：原子化证据卡，跨子任务共享的核心数据单元。

关键字段建议：

- `id` bigint pk
- `card_uid` varchar(96) unique not null — 全局唯一标识
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `produced_by_subtask` varchar(32) not null — 产出该证据的子任务
- `claim` text not null — 原子事实断言
- `claim_type` enum(`NUMERIC`, `CAUSAL`, `DESCRIPTIVE`, `TEMPORAL`) not null
- `entities_json` json — 涉及的实体列表
- `source_id` varchar(64) not null — 原始来源标识
- `source_type` enum(`VECTOR_DB`, `ES`, `SQL_DB`, `KNOWLEDGE_GRAPH`, `WEB`) not null
- `reliability_tier` enum(`T1`, `T2`, `T3`) not null — T1=权威系统, T2=内部文档, T3=外部
- `data_freshness` date — 数据截止日期
- `retrieval_score` decimal(4,3) — 重排分数
- `confidence` decimal(4,3) — 单卡置信度
- `corroborated_by_json` json — 佐证来源列表
- `conflicts_with_json` json — 冲突证据卡列表
- `consumed_by_json` json — 消费该证据的子任务列表
- `created_at` datetime not null

索引建议：

- `index(tenant_id, task_id, plan_version, produced_by_subtask)`
- `index(tenant_id, task_id, plan_version, claim_type)`

### 5.6 `evidence_evaluations`

用途：每轮证据充分性评估的三维打分记录。

关键字段建议：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `subtask_code` varchar(32) not null
- `iteration` int not null
- `coverage_score` decimal(4,3) not null
- `conflict_score` decimal(4,3) not null
- `confidence_score` decimal(4,3) not null
- `total_score` decimal(4,3) not null
- `threshold_used` decimal(4,3) not null
- `verdict` enum(`SUFFICIENT`, `INSUFFICIENT`, `NEED_CLARIFICATION`) not null
- `gap_type` varchar(64) — coverage_gap / conflict_gap / confidence_gap
- `gap_detail` text
- `action_taken` varchar(256) — 纠偏动作描述
- `rips_json` json — Required Information Points 及覆盖状态
- `created_at` datetime not null

唯一约束建议：

- `unique(task_id, plan_version, subtask_code, iteration)`
- `index(tenant_id, task_id, plan_version, subtask_code)`

### 5.7 `subtask_outputs`

用途：子任务的候选答案与三重校验结果。

关键字段建议：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `task_id` bigint not null
- `plan_version` int not null
- `subtask_code` varchar(32) not null
- `draft_answer` text not null — 候选答案
- `claims_json` json — 从答案中提取的断言列表
- `factual_consistency_score` decimal(4,3) — 事实一致性分数
- `factual_detail_json` json — 每条 claim 的 SUPPORTED/NOT_SUPPORTED/CONTRADICTED
- `sensitive_hits_json` json — 敏感信息命中详情
- `citation_coverage` decimal(4,3) — 引用覆盖率
- `citation_accuracy` decimal(4,3) — 引用准确率
- `verify_verdict` enum(`PASS`, `FAIL_FACTUAL`, `FAIL_SENSITIVE`, `FAIL_CITATION`) not null
- `created_at` datetime not null

唯一约束建议：

- `unique(task_id, plan_version, subtask_code)`
- `index(tenant_id, task_id, plan_version, subtask_code)`

### 5.8 `sessions` 与 `session_turns`

用途：会话级情景记忆，支持指代消解和跨轮次上下文。

`sessions` 关键字段：

- `id` bigint pk
- `session_id` varchar(64) unique not null
- `user_id` varchar(64) not null
- `tenant_id` varchar(64) not null
- `topic` varchar(256) — 会话主题（自动提取）
- `mentioned_entities_json` json — 跨轮次累积的实体
- `intent_pattern` varchar(128) — 用户意图模式
- `status` enum(`ACTIVE`, `ARCHIVED`) not null
- `created_at` datetime not null
- `updated_at` datetime not null
- `archived_at` datetime

`session_turns` 关键字段：

- `id` bigint pk
- `tenant_id` varchar(64) not null
- `session_id` varchar(64) not null
- `turn_no` int not null
- `user_query` text not null
- `resolved_query` text — 指代消解后
- `task_id` bigint — 关联的 search_task
- `summary` text — 本轮摘要
- `key_entities_json` json
- `created_at` datetime not null

唯一约束建议：

- `unique(session_id, turn_no)`
- `index(tenant_id, session_id, turn_no)`

## 6. 状态机设计

### 6.1 全局任务状态

`search_tasks.status`：

```
PENDING → PLANNING → EXECUTING → COMPLETED
                 ↑          ↓
                 ←── (replan) ──
                            ↓
                         FAILED
                            ↓
                        DEGRADED
```

- `PENDING`：请求已接收，等待 Planner
- `PLANNING`：Planner 正在生成/重生成 DAG
- `EXECUTING`：DAG 正在调度执行
- `COMPLETED`：所有子任务完成，最终答案已生成
- `FAILED`：不可恢复的失败
- `DEGRADED`：超限降级，返回部分结果

### 6.2 子任务状态

`subtasks.status`：

```
PENDING → READY → RUNNING → COMPLETED
                     ↓
                   FAILED → (触发纠偏或升级)
                     ↓
                   SKIPPED → (被 replan 移除)
```

- `PENDING`：等待前置依赖完成
- `READY`：所有依赖已满足，可被调度
- `RUNNING`：正在执行
- `COMPLETED`：证据评估通过 + 输出校验通过
- `FAILED`：局部纠偏超限，升级到全局
- `SKIPPED`：被 replan 移除或软依赖降级跳过

### 6.3 调度器状态流转规则

```python
# 伪代码：Scheduler 核心逻辑
def schedule_next(task_id, plan_version):
    # 1. 计算入度
    subtasks = get_subtasks(task_id, plan_version)
    for st in subtasks:
        if st.status == 'PENDING':
            deps = get_dependencies(st)
            all_satisfied = all(
                dep.status in ('COMPLETED', 'SKIPPED')
                if dep.type == 'HARD'
                else dep.status in ('COMPLETED', 'SKIPPED', 'FAILED')
                for dep in deps
            )
            if all_satisfied:
                st.status = 'READY'

    # 2. 从就绪队列取任务，按 priority 排序
    ready = [st for st in subtasks if st.status == 'READY']
    ready.sort(key=lambda x: x.priority)

    # 3. 并发度控制
    running_count = count_running(task_id)
    available_slots = MAX_CONCURRENT - running_count

    for st in ready[:available_slots]:
        execution_id = new_execution_id(task_id, plan_version, st.subtask_code)
        claimed = claim_subtask_for_execution(
            task_id=task_id,
            plan_version=plan_version,
            subtask_code=st.subtask_code,
            expected_status="READY",
            execution_id=execution_id,
        )
        if not claimed:
            continue  # 其他调度分支已抢到，不重复分发
        dispatch_to_celery(st, execution_id=execution_id)
```

Worker 完成后回写结果时，必须同时校验 `tenant_id + task_id + plan_version + subtask_code + execution_id`；若当前活动计划版本已切换，则旧结果只允许落库审计或进入候选证据区，不能直接推进新 DAG。

### 6.4 状态机边界情况处理

生产环境中以下边界情况必然发生，需要明确处理策略：

#### 6.4.1 Stuck RUNNING Reaper（卡死任务收割）

子任务可能因 Worker 崩溃、网络分区等原因永远停留在 RUNNING 状态。

处理方案：Celery Beat 定时任务（每 60s）扫描超时的 RUNNING 子任务：

```python
# 伪代码：stuck_running_reaper
def reap_stuck_tasks():
    stuck = db.query(Subtask).filter(
        Subtask.status == "RUNNING",
        Subtask.started_at < now() - Subtask.timeout_ms * 2  # 超过 2 倍超时
    ).all()
    for st in stuck:
        st.status = "FAILED"
        st.last_error_code = "STUCK_RUNNING_TIMEOUT"
        st.last_error_message = f"Task stuck in RUNNING for >{st.timeout_ms * 2}ms"
        # 释放 Redis 执行锁
        redis.delete(f"rag:search:{st.tenant_id}:subtask:{st.task_id}:{st.subtask_code}:exec")
        # 触发恢复编排，重新评估下一步
        resume_orchestrator.apply_async(args=[st.tenant_id, st.task_id])
```

#### 6.4.2 MySQL-Redis 状态不一致恢复

MySQL 是真理源，Redis 是热缓存。不一致时以 MySQL 为准。

恢复时机：
1. 应用启动时（Worker/API 进程启动）
2. Redis 故障恢复后
3. 定时对账（Celery Beat 每 5 分钟）

```python
def rebuild_redis_hot_cache(tenant_id: str, task_id: int):
    """从 MySQL 重建 Redis 热缓存"""
    task = db.query(SearchTask).get(task_id)
    if task.status not in ("EXECUTING", "PLANNING"):
        return  # 只重建活跃任务

    # 重建全局任务状态
    redis.hset(f"rag:search:{tenant_id}:task:{task_id}:state", mapping={...})
    # 重建 DAG 入度表
    rebuild_indegree_from_mysql(tenant_id, task_id, task.active_plan_version)
    # 重建证据池
    rebuild_evidence_pool_from_mysql(tenant_id, task_id)
```

#### 6.4.3 并发 Replan 竞争

多个子任务同时失败可能触发多次 Replan 请求。必须保证同一时刻只有一个 Replan 在执行。

```python
REPLAN_LOCK_KEY = "rag:search:{tenant_id}:replan:{task_id}"
REPLAN_LOCK_TTL = 30  # 秒

def try_replan(tenant_id: str, task_id: int, reason: str) -> bool:
    """尝试获取 Replan 锁，保证互斥"""
    acquired = redis.set(REPLAN_LOCK_KEY.format(tenant_id=tenant_id, task_id=task_id),
                         value=reason, nx=True, ex=REPLAN_LOCK_TTL)
    if not acquired:
        logger.info(f"Replan already in progress for task {task_id}, skipping")
        return False
    try:
        # 在 MySQL 事务内切换 active_plan_version，旧 plan 的回写结果统一做 stale result fencing
        do_replan(tenant_id, task_id, reason)
    finally:
        redis.delete(REPLAN_LOCK_KEY.format(tenant_id=tenant_id, task_id=task_id))
    return True
```

#### 6.4.4 预算耗尽处理

预算耗尽时不立即中断正在执行的子任务，而是允许当前迭代完成，不再发起新调用：

1. 每个 LangGraph 节点执行前检查预算（参见 [codex_技术拆解 Section 3.6](./codex_技术拆解.md#state-redis)）。
2. 预算耗尽 → 设置 `next_action = "fallback"`，当前正在执行的子任务允许完成当前迭代。
3. Scheduler 不再分发新的子任务。
4. 等待所有 RUNNING 子任务完成后，进入 Fallback 降级输出。

## 7. 子任务执行闭环设计

### 7.1 执行流程

每个子任务在 Local Loop 中经历以下阶段：

```mermaid
flowchart TD
    Start["子任务开始"] --> CacheProbe{"语义缓存探测"}
    CacheProbe -- "命中" --> FreshnessCheck{"缓存时效校验<br/>TTL / 数据新鲜度"}
    FreshnessCheck -- "新鲜" --> InjectEvidence["注入缓存证据卡"]
    FreshnessCheck -- "过期" --> RewriteRoute
    CacheProbe -- "未命中" --> RewriteRoute["改写路由决策"]

    RewriteRoute --> QV["语义增强改写"]
    RewriteRoute --> QK["精准术语提取"]
    RewriteRoute --> QS["结构化翻译"]
    RewriteRoute --> QG["图查询规划"]
    RewriteRoute --> QW["外部检索准备"]

    QV & QK & QS & QG & QW --> Retrieval["多路并发检索"]
    Retrieval --> Merge["证据汇聚+去重"]
    Merge --> Fusion["RRF排序融合"]
    Fusion --> Rerank["轻量重排→深度重排"]
    Rerank --> Compress["证据压缩与原子化"]

    Compress --> EvalScore["三维评估打分"]
    InjectEvidence --> EvalScore
    EvalScore --> Threshold{"阈值判定"}

    Threshold -- "充分" --> ParentHydration["父文档按需召回"]
    ParentHydration --> DraftClaims["生成候选答案"]
    DraftClaims --> Verify{"三重校验"}
    Verify -- "通过" --> CacheWrite["缓存回写"]
    CacheWrite --> Done["子任务完成"]

    Verify -- "事实不一致" --> RetryFactual["重新生成答案"]
    Verify -- "敏感信息" --> RetrySensitive["脱敏处理"]
    Verify -- "引用不对齐" --> RetryCitation["重新标注引用"]
    RetryFactual & RetrySensitive & RetryCitation --> LocalGuard2{"迭代守卫"}
    LocalGuard2 -- "允许" --> DraftClaims
    LocalGuard2 -- "超限" --> Escalate

    Threshold -- "不充分" --> GapDiag["缺口诊断"]
    GapDiag -- "可补检" --> GapMap["缺口→纠偏动作映射"]
    GapDiag -- "需用户补充" --> Clarify["追问关键缺失信息"]
    Clarify --> ToPlanner["返回主规划器"]
    GapMap --> LocalGuard{"迭代守卫"}
    LocalGuard -- "允许" --> RewriteRoute
    LocalGuard -- "超限" --> Escalate["升级到全局重规划<br/>含：迭代次数/最佳分数/缺口类型/已收集证据/建议"]
```

> **ParentHydration 实现依赖**：父文档按需召回依赖向量库的 parent-child 索引结构（即文档切片时保留 parent_id 关联），检索时先命中 child chunk，再通过 parent_id 召回完整父文档上下文。

### 7.2 改写路由映射

| 缺口类型 | 激活改写 | 检索通道 | 说明 |
|---------|---------|---------|------|
| 语义推理 | QV（HyDE/多查询） | 向量库 | 默认路由，覆盖大部分场景 |
| 术语歧义 | QK（同义词扩展） | ES 全文 | 企业术语、别名、缩写 |
| 数值/统计 | QS（Schema Linking） | SQL/数仓 | 需要精确数值的场景 |
| 多跳关联 | QG（实体关系） | 图数据库 | 关联链路问题 |
| 时效缺口 | QW（时间约束） | Web 搜索 | 内部库无最新信息 |

> **改写策略参考**：ES 全文检索的 6 种改写策略详见 [AI_Agent指令.md Section 2.2.3](../../AI_Agent指令.md)；Milvus 向量检索的改写策略详见 [AI_Agent指令.md Section 2.2.2](../../AI_Agent指令.md)。

### 7.3 证据压缩四步流程

1. **去噪**：Cross-Encoder 对每条证据的每个句子与子任务 query 做相关性打分，relevance < 0.3 丢弃
2. **去冗余**：Embedding 聚类（余弦 ≥ 0.85），同簇取信息密度最高的版本，记录被合并来源
3. **原子化**：LLM 将每条证据拆分为不可再分的原子事实（Atomic Claim），每个 claim 只表达一个独立可验证的事实断言
4. **结构化**：封装为标准证据卡 Schema，附带元数据（来源、可靠性层级、时效性、重排分数）

### 7.4 证据充分性评估

三维打分公式：

```
总分 = w1 × Coverage + w2 × Conflict + w3 × Confidence

业务场景权重配置：
  财务/合规类（高精度）：w1=0.4, w2=0.35, w3=0.25, 阈值=0.85
  一般业务咨询：       w1=0.4, w2=0.25, w3=0.35, 阈值=0.70
  探索性分析：         w1=0.5, w2=0.15, w3=0.35, 阈值=0.60
```

各维度计算方式：

- **Coverage** = 已覆盖 RIP 数 / 总 RIP 数（LLM 提取 Required Information Points）
- **Conflict** = 1 - (严重冲突数 × 1.0 + 中等冲突数 × 0.3) / 总证据对数
- **Confidence** = Σ(top-K 卡置信度) / K，其中单卡置信度 = reliability_weight × retrieval_score × freshness_decay

freshness_decay 按数据类型区分：

> **变更说明**：freshness_decay 采用指数衰减（半衰期模型 `2^(-days/half_life)`）而非线性衰减。原因：线性衰减在数据过期边界处会出现突变（从正值直接跳到 0），不符合数据价值随时间平滑递减的实际规律。指数衰减通过 `floor` 参数保证即使很旧的数据也保留最低权重，避免完全丢弃仍有参考价值的历史证据。

> **状态命名一致性确认**：两份文档统一使用以下状态命名——全局任务：`PENDING`/`PLANNING`/`EXECUTING`/`COMPLETED`/`FAILED`/`DEGRADED`；子任务：`PENDING`/`READY`/`RUNNING`/`COMPLETED`/`FAILED`/`SKIPPED`。其中 `READY` 表示依赖已满足可被调度（区别于 `PENDING` 等待依赖），`COMPLETED` 表示成功完成（不使用 `success`）。

```python
def freshness_decay(data_type: str, days: int) -> float:
    configs = {
        "financial": {"half_life": 30, "floor": 0.3},
        "policy":    {"half_life": 180, "floor": 0.5},
        "market":    {"half_life": 7, "floor": 0.2},
    }
    cfg = configs.get(data_type, {"half_life": 90, "floor": 0.4})
    return max(cfg["floor"], 2 ** (-days / cfg["half_life"]))
```

### 7.5 输出三重校验

| 校验维度 | 方法 | 阈值 | 不通过处理 |
|---------|------|------|-----------|
| 事实一致性 | Claim extraction + NLI 蕴含检测 | ≥ 0.9 | 标记 NOT_SUPPORTED 的 claim，要求 LLM 重新生成 |
| 敏感信息 | 正则 PII + 关键词黑名单 + ACL 回查 + LLM 兜底 | 0 hit | 自动脱敏或降级输出 |
| 引用对齐 | 检查 [EC-xxx] 标注的覆盖率和准确率 | 均 ≥ 0.95 | 强制 LLM 重新标注引用 |

## 8. 记忆系统设计

### 8.1 五层记忆总览

| 层级 | 名称 | 用途 | 存储 | 生命周期 |
|-----|------|------|------|---------|
| L1 | 上下文窗口 | 当前 LLM 调用的 prompt | 内存 | 单次调用 |
| L2 | 工作记忆 | 当前子任务的证据卡、评估历史、纠偏记录 | 内存 + Redis | 子任务完成后压缩上提 |
| L3 | 任务状态 | DAG 状态、全局证据池、预算消耗 | Redis + MySQL | 任务完成后归档 |
| L4 | 会话记忆 | 本次对话的交互轨迹、已完成子任务摘要 | Redis + MySQL | 会话结束后归档 |
| L5 | 长期记忆 | 用户画像、查询模式、语义缓存 | MySQL + 向量库 + Redis（接口预留） | 永久/TTL 淘汰 |

### 8.2 L1 上下文窗口组装策略

目标：每个 Agent 只看到它需要的最小上下文（≤ 8K tokens）。

```
┌── Agent Context Window ──────────────────────┐
│  [System Prompt]        ~500 tokens           │
│  [Task Brief]           ~300 tokens (从L3)    │
│  [Evidence Cards]       ~3000 tokens (从L2)   │
│  [Iteration Context]    ~500 tokens (仅重试)  │
│  [Conversation Summary] ~500 tokens (从L4)    │
│  [User Query]           ~200 tokens           │
└───────────────────────────────────────────────┘
```

裁剪优先级（超出时按此顺序截断）：Conversation Summary → 低分证据卡 → Iteration Context。

### 8.3 L2 工作记忆持久化策略

关键改进：不等子任务完成才同步，每次迭代结束后增量 checkpoint 到 Redis。

```
Redis Key: rag:search:{tenant_id}:subtask:{task_id}:{subtask_code}:memory
Redis Type: Hash
Fields:
  iteration       → 当前迭代次数
  evidence_pool   → JSON(证据卡列表)
  eval_history    → JSON(评估历史)
  budget_consumed → JSON(消耗统计)
  draft_claims    → JSON(候选答案，可为空)
TTL: 1 hour（子任务完成后删除）
```

### 8.4 L3 全局证据池共享机制

```
子任务 A 完成 → 将证据卡写入 evidence_cards 表 + Redis 缓存
子任务 B 开始 → 先从全局证据池检查是否有可复用证据
             → 有 → 直接注入 L2，跳过检索
             → 无 → 正常走检索流程
```

Redis 缓存结构：

```
Redis Key: rag:search:{tenant_id}:task:{task_id}:evidence
Redis Type: Hash
Field: {card_uid} → JSON(证据卡摘要)
TTL: 与任务生命周期一致
```

### 8.5 L4 会话记忆首版方案

首版采用滑动窗口 + 渐进式摘要（覆盖 90% 场景），不急于引入向量检索和知识图谱：

1. 保留最近 N 轮原始对话（滑动窗口，N=5）
2. 超出窗口的轮次用 LLM 生成摘要替换原始消息
3. 每轮提取 key_entities，合并到 session_context 用于指代消解

> **L4 通道 C/D 和 L5 接口预留**：首版 L4 只实现通道 A（滑动窗口）和 B（渐进式摘要）。通道 C（向量检索历史对话）和通道 D（知识图谱实体关联）在 Port 层预留接口定义（`SessionMemoryPort.search_similar_turns()`、`SessionMemoryPort.get_entity_context()`），首版返回空结果。L5 长期记忆（用户画像、语义缓存）同理，Port 接口先定义，实现延后。

### 8.6 Redis 存储规范总览

所有 Key 统一前缀 `rag:search:{tenant_id}:`，按功能域分层。完整 Key 命名规范、数据类型和 TTL 策略见 [codex_技术拆解 Section 3.1](./codex_技术拆解.md#state-redis)。

核心 Key 一览：

| 功能域 | Key 模式 | 数据类型 |
|--------|----------|----------|
| 全局任务状态 | `rag:search:{tenant_id}:task:{task_id}:state` | Hash |
| DAG 入度表 | `rag:search:{tenant_id}:task:{task_id}:plan:{ver}:indegree` | Hash |
| 子任务工作记忆 | `rag:search:{tenant_id}:subtask:{task_id}:{code}:memory` | Hash |
| 全局证据池 | `rag:search:{tenant_id}:task:{task_id}:evidence` | Hash |
| 预算消耗 | `rag:search:{tenant_id}:task:{task_id}:budget` | Hash |

### 8.7 状态变更事件流

首版采用 **Celery 结果回写 + 恢复编排**，不引入 Redis Stream，也不使用 Celery `on_success` 直接链式调度下游。

事件流路径：

1. `scheduler/executor` 为 READY 子任务生成 `execution_id`，条件更新 MySQL 为 `RUNNING`，并分发 Celery。
2. Celery Worker 内部运行 `SubtaskGraph`，完成后把结果写回 MySQL，并同步刷新 Redis 热缓存/L2-L3 记忆。
3. Worker 完成后投递轻量 `resume_orchestrator(tenant_id, task_id, plan_version, subtask_code, execution_id)`。
4. `resume_orchestrator` 从 MySQL 真理源 + Redis 热缓存恢复 `GlobalGraph`，决定是继续 `scheduler`、进入 `step_gate`、触发 `replan` 还是 `output`。

选择这种方式的原因：避免 LangGraph 编排、Celery callback 链和 Redis Stream 三套机制并存；首版只保留一条“Worker 回写结果 → 恢复编排继续推进”的路径。详细实现见 [codex_技术拆解 Section 3.7](./codex_技术拆解.md#state-redis)。

### 8.8 Scheduler 就绪任务发现机制

Scheduler 的核心仍可利用 Redis Lua 脚本实现原子递减入度 + READY 热判定，但 READY 判定最终必须以 MySQL 当前 `active_plan_version` 和子任务状态为准：

1. `planner` 生成 DAG 后，将入度写入 MySQL 和 Redis 热缓存。
2. `resume_orchestrator` 处理子任务完成结果时，先校验 `tenant_id + task_id + plan_version + subtask_code + execution_id`。
3. 校验通过后，再用 Lua 对当前 `plan_version` 的入度缓存做原子递减；缓存 miss 或 Redis 异常时回退 MySQL 重算。
4. 新就绪任务列表生成后，再通过 MySQL 乐观锁逐个 claim 为 `RUNNING` 并分发 Celery。
5. 如果没有新 READY 且无 RUNNING，则进入 `step_gate`；仍有 `PENDING` 但无 `RUNNING` 时进入死锁检测/重规划。

完整 Lua 脚本和流程图见 [codex_技术拆解 Section 3.3 和 3.8](./codex_技术拆解.md#state-redis)。

## 9. 一致性与并发控制设计

### 9.1 并发控制总体策略

| 场景 | 方案 | 说明 |
|------|------|------|
| DAG 状态更新（入度计算） | MySQL 真理源 + Redis 原子热缓存（HINCRBY + Lua） | READY 判定优先读热缓存，失配时回退 MySQL |
| 语义缓存写入 | Redis SET NX | 防止并发重复写入 |
| 预算扣减 | Redis HINCRBY | 原子递增 |
| Replan 时热替换 DAG | Redis 分布式锁（短 TTL） + MySQL 事务切换 `active_plan_version` | 防止 Scheduler 调度旧 DAG 任务 |
| 子任务状态流转 | MySQL 乐观锁（row_version） | 防止重复执行 |
| 子任务结果回写 | `execution_id + plan_version` 条件更新 | 防止旧执行结果污染新计划 |

### 9.2 MySQL 负责什么

1. 子任务状态从 `READY` → `RUNNING` 的原子更新（`WHERE tenant_id=? AND task_id=? AND plan_version=? AND subtask_code=? AND status='READY' AND row_version=?`），并同步写入 `current_execution_id`
2. Replan 时在事务内切换 `search_tasks.active_plan_version`，确保旧计划结果不会推进新 DAG
3. 证据卡、评估记录和输出结果按 `tenant_id + task_id + plan_version` 持久化
4. 全局任务状态的最终一致性保障，以及 Redis 热缓存的重建依据

### 9.3 Redis 负责什么

1. DAG 调度的热数据（入度缓存、就绪判断辅助）
2. 子任务执行的抢占锁（防止同一子任务被多个 Worker 执行）
3. L2/L3 的热数据缓存
4. 预算消耗的实时追踪

锁 Key 建议：

```
rag:search:{tenant_id}:subtask:{task_id}:{subtask_code}:exec  — 子任务执行锁
rag:search:{tenant_id}:replan:{task_id}                       — Replan 互斥锁
rag:search:{tenant_id}:task:{task_id}:resume                  — 恢复编排锁
```

锁策略：短 TTL（30-60s），Worker 长任务需心跳续租，释放前校验 owner token。

### 9.4 幂等性设计

1. 子任务每次迭代生成唯一 `execution_id = {tenant_id}:{task_id}:{plan_version}:{subtask_code}:iter{N}`
2. 检索结果和 LLM 输出以 `execution_id` 为 key 缓存到 Redis
3. Worker 重启时先检查缓存，命中则跳过
4. 证据卡以 `card_uid` 做唯一约束，重复写入自动去重
5. 状态流转使用"期望旧状态 → 新状态"的条件更新
6. Worker 回写时必须同时校验 `execution_id` 和 `plan_version`；校验失败视为 stale result，只落审计不推进主流程

### 9.5 多层超时设计

```
单次 LLM 调用超时：    5-15s（按模型区分）
单路检索超时：         3-10s（按数据源区分）
子任务总超时：         30-60s（含多次纠偏迭代）
全局任务超时：         120-300s（SLA 级别配置）
```

### 9.6 熔断策略

对 LLM Provider、向量库、ES、图数据库、Web 搜索分别维护熔断状态：

1. 连续失败 N 次（默认 3 次）→ 打开熔断，暂停该通道
2. 熔断期间任务不丢弃，使用 Celery countdown 延后重试
3. 熔断窗口（默认 30s）过后进入半开状态，放行一个探测请求
4. 探测成功 → 关闭熔断；探测失败 → 继续熔断

### 9.7 Celery 高并发适配性分析

Celery 在本场景的定位是"异步任务执行引擎"，不是消息队列本身。首版为什么够用：

1. 目标并发度是中小企业级别（QPS 10-100），Celery + Redis Broker 完全没有压力。
2. 当前仓库已有完整的 Celery 模式示例（prefork/gevent/aio 三种 pool），落地路径最短。
3. Celery 的治理能力（重试、路由、Beat、Flower 监控）开箱即用。

真实瓶颈在 prefork 进程开销（每个 worker ~50-100MB）和 Redis Broker 单线程（QPS 10K+ 才触及）。详细分析见 [codex_技术拆解 Section 4](./codex_技术拆解.md#celery-concurrency)。

### 9.8 Pool 选型建议

按任务类型选择不同的 Celery Pool：

| 任务类型 | 队列 | 推荐 Pool | 原因 |
|----------|------|-----------|------|
| LLM API 调用 | `llm_jobs` | celery-aio-pool | IO 等待为主，原生 asyncio |
| 向量检索 / ES 检索 | `retrieval_jobs` | celery-aio-pool | 网络 IO 为主 |
| 证据压缩 / NLI 推理 | `compute_jobs` | prefork | CPU 密集 |
| 子任务编排 | `orchestrate_jobs` | solo | 轻量调度 |

### 9.9 未来演进路径

1. 当 QPS > 500 或需要更细粒度的异步控制时，考虑 `taskiq`（原生 async）或 `arq`。
2. LangGraph 自身的 async node 可以逐步替代部分 Celery 编排职责。
3. Redis Broker 成为瓶颈时可切换到 RabbitMQ 或 Kafka。
4. K8s 扩展时按 Worker Lane 独立部署 Deployment，通过 HPA 按队列积压量自动扩缩。

### 9.10 错误分类与降级规则

当前没有错误分类，无法区分可重试和不可重试错误。生产环境中必须明确每类错误的处理策略。

#### 错误分类表

| 分类 | 典型场景 | 处理策略 | `last_error_code` 示例 |
|------|---------|---------|----------------------|
| TRANSIENT（瞬态） | 网络超时、LLM 限流（429）、Redis 连接断开 | 指数退避重试，最多 3 次（1s → 2s → 4s） | `LLM_TIMEOUT`, `LLM_RATE_LIMITED`, `REDIS_CONN_ERROR`, `RETRIEVAL_TIMEOUT` |
| PERMANENT（永久） | 参数错误、权限不足、模型不存在、查询语法错误 | 不重试，直接标记 FAILED，写入错误详情 | `INVALID_QUERY`, `AUTH_DENIED`, `MODEL_NOT_FOUND`, `SCHEMA_ERROR` |
| DEGRADABLE（可降级） | 某检索通道不可用、某改写策略失败、缓存不可用 | 跳过该通道/策略，用其他通道补偿 | `CHANNEL_UNAVAILABLE`, `REWRITE_FAILED`, `CACHE_UNAVAILABLE` |

#### `last_error_code` 枚举定义

```python
class ErrorCode(str, Enum):
    # TRANSIENT
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    REDIS_CONN_ERROR = "REDIS_CONN_ERROR"
    RETRIEVAL_TIMEOUT = "RETRIEVAL_TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"

    # PERMANENT
    INVALID_QUERY = "INVALID_QUERY"
    AUTH_DENIED = "AUTH_DENIED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

    # DEGRADABLE
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    REWRITE_FAILED = "REWRITE_FAILED"
    CACHE_UNAVAILABLE = "CACHE_UNAVAILABLE"
    CHECKPOINT_WRITE_FAILED = "CHECKPOINT_WRITE_FAILED"
```

#### DEGRADED 状态规则

子任务失败时，是否允许全局任务降级取决于失败子任务的性质：

| 场景 | 处理 | 说明 |
|------|------|------|
| 非核心子任务失败（SOFT 依赖的下游） | 允许 DEGRADED | 跳过该子任务，用已有证据生成部分回答 |
| 核心子任务失败但有部分证据 | 允许 DEGRADED | 标注不确定性，建议用户补充 |
| 核心子任务失败且无证据 | 必须 FAILED | 无法生成有意义的回答 |
| 所有检索通道均不可用 | 必须 FAILED | 系统级故障 |

全局任务进入 `DEGRADED` 时，`final_answer` 必须包含：已覆盖的信息点、未覆盖的信息点、降级原因、建议的下一步操作。

## 10. LangGraph 作为 DAG 编排引擎

### 10.1 选型理由

LangGraph 原生支持条件边、状态持久化、并行执行（`Send()`）和 Checkpoint 恢复，这些能力如果手写需要大量基础设施代码。详细对比见 [codex_技术拆解 Section 2.1](./codex_技术拆解.md#langgraph-dag)。

### 10.2 两图架构

采用 GlobalGraph + SubtaskGraph 两层嵌套：

1. **GlobalGraph**：负责 Intake → Planner → Scheduler → StepGate → Replan/Output 的主流程。节点包括 `intake`、`planner`、`scheduler`、`executor`、`step_gate`、`replan`、`loop_guard`、`fallback`、`output`。
2. **SubtaskGraph**：负责 Router → Cache → Rewrite → Retrieval → Eval → Verify/Retry 的局部循环。节点包括 `router`、`cache_probe`、`rewrite`、`retrieve`、`post_process`、`evaluate`、`verify`、`retry`。
3. **嵌套方式**：GlobalGraph 的 `executor` 节点登记 `execution_id` 并分发 Celery；Celery Worker 内部运行 `SubtaskGraph`，完成后回写结果并恢复 `GlobalGraph`。

### 10.3 State Schema 概要

GlobalGraph 和 SubtaskGraph 各自定义 `TypedDict` 状态，所有节点共享同一份状态。关键字段包括任务标识、控制平面参数、DAG 结构、子任务结果、证据池、流程控制信号。完整定义见 [codex_技术拆解 Section 2.3-2.5](./codex_技术拆解.md#langgraph-dag)。

### 10.4 与 Celery 的分工

1. **LangGraph 管编排逻辑**：节点定义、条件路由、状态传递、并行分发、checkpoint。运行在 API 进程或轻量 Worker 中。
2. **Celery 管重型异步任务**：LLM API 调用、向量检索、ES 检索、证据压缩等 IO/CPU 密集操作。运行在独立 Worker 进程中。
3. **交互方式**：LangGraph 的 `executor` 节点登记执行实例并分发 Celery；Celery Worker 完成后写回结果，再由 `resume_orchestrator` 恢复 `GlobalGraph` 继续推进。

详细分工边界和代码示例见 [codex_技术拆解 Section 2.9](./codex_技术拆解.md#langgraph-dag)。

## 11. 模块分层建议

```mermaid
flowchart TB
    API["HTTP API / 轮询查询<br/>可选 WebSocket"]
    WORKER["Celery Workers<br/>Planner / Scheduler / Executor / Evaluator"]
    APP["Application Services<br/>SearchOrchestrator / PlanService / SubtaskService / EvidenceService"]
    DOMAIN["Domain Models<br/>状态机 / DAG / 证据评估策略 / 预算策略"]
    PORTS["Ports<br/>LLMPort / VectorStorePort / SearchStorePort<br/>GraphStorePort / WebSearchPort / CachePort"]
    REPO["Repositories<br/>TaskRepo / SubtaskRepo / EvidenceRepo / SessionRepo"]
    INFRA["Infrastructure Adapters<br/>MySQL / Redis / Celery / Mock LLM / Mock Stores"]
    EXT[("MySQL / Redis / 外部服务")]

    API --> APP
    WORKER --> APP
    APP --> DOMAIN
    APP --> PORTS
    APP --> REPO
    REPO --> INFRA
    PORTS --> INFRA
    INFRA --> EXT
```

推荐边界：

1. `interface` 层：入参校验、响应封装、轮询查询接口，以及可选的 WebSocket 流式推送。
2. `application` 层：编排全局循环和子任务循环，调用仓储，管理预算，触发状态流转。
3. `domain` 层：DAG 拓扑排序、状态机规则、证据评估算法、缺口诊断映射、预算策略。
4. `ports` 层：声明外部能力协议（LLM、向量库、ES、图数据库、Web 搜索、缓存），不出现具体 SDK。
5. `infrastructure` 层：MySQL 仓储、Redis 缓存、Celery 适配器、Mock 实现。
6. `workers` 层：Celery 任务入口，不堆业务逻辑，真正逻辑落在 application 层。

### 11.1 配置管理说明

采用 Pydantic Settings 管理配置，支持环境变量覆盖，所有阈值类配置不硬编码：

```python
from pydantic_settings import BaseSettings

class AppSettings(BaseSettings):
    # --- 数据库 ---
    mysql_url: str = "mysql+asyncmy://user:pass@localhost:3306/agentic_rag"
    redis_url: str = "redis://:123456@localhost:6379/0"
    redis_checkpoint_url: str = "redis://:123456@localhost:6379/1"

    # --- 全局控制 ---
    max_global_iterations: int = 3
    max_concurrent_subtasks: int = 3
    max_replan_count: int = 2
    default_subtask_max_iterations: int = 3

    # --- 超时（ms） ---
    default_subtask_timeout_ms: int = 30000
    global_task_timeout_ms: int = 120000
    llm_call_timeout_s: int = 15

    # --- 证据评估阈值 ---
    eval_threshold_general: float = 0.70
    eval_threshold_financial: float = 0.85
    eval_threshold_exploratory: float = 0.60
    replan_similarity_threshold: float = 0.8
    replan_marginal_gain_threshold: float = 0.03

    # --- 熔断 ---
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_window_s: int = 30

    # --- Celery ---
    celery_broker_url: str = "redis://:123456@localhost:6379/2"
    celery_result_backend: str = "redis://:123456@localhost:6379/3"

    class Config:
        env_prefix = "RAG_"  # 环境变量前缀：RAG_MYSQL_URL, RAG_REDIS_URL 等
        env_file = ".env"
```

> **原则**：所有在 Section 7.4、9.5、9.6 中出现的数值阈值，都必须通过 `AppSettings` 读取，不允许在业务代码中硬编码。

### 11.2 推荐目录结构

```
用户AgenticRAG检索/
├── config/
│   ├── settings.py          # 配置管理
│   └── enums.py             # 枚举定义
├── domain/
│   ├── dag.py               # DAG 拓扑排序、调度算法
│   ├── state_machine.py     # 状态机规则
│   ├── evidence_eval.py     # 证据评估算法（三维打分）
│   ├── gap_diagnosis.py     # 缺口诊断与纠偏映射
│   ├── budget.py            # 预算策略
│   └── replan_guard.py      # Replan 循环检测
├── ports/
│   ├── llm_port.py          # LLM 调用抽象
│   ├── vector_store_port.py
│   ├── search_store_port.py
│   ├── graph_store_port.py
│   ├── web_search_port.py
│   ├── cache_port.py
│   └── task_queue_port.py
├── application/
│   ├── search_orchestrator.py   # 全局循环编排
│   ├── plan_service.py          # Planner 调用与 DAG 生成
│   ├── subtask_service.py       # 子任务执行闭环
│   ├── evidence_service.py      # 证据管理与共享
│   ├── rewrite_service.py       # 查询改写
│   ├── retrieval_service.py     # 多路检索执行
│   ├── verify_service.py        # 输出三重校验
│   └── session_service.py       # 会话记忆管理
├── infrastructure/
│   ├── models.py            # SQLAlchemy ORM 模型
│   ├── repositories.py      # MySQL 仓储实现
│   ├── redis_cache.py       # Redis 缓存与锁
│   ├── celery_adapter.py    # Celery 任务适配器
│   └── mock/
│       ├── mock_llm.py
│       ├── mock_vector_store.py
│       ├── mock_search_store.py
│       ├── mock_graph_store.py
│       └── mock_web_search.py
├── workers/
│   ├── planner_worker.py    # Planner Celery 任务
│   ├── executor_worker.py   # 子任务执行 Celery 任务
│   ├── evaluator_worker.py  # 证据评估 Celery 任务
│   └── scheduler_worker.py  # 调度器 Celery Beat 任务
├── interface/
│   ├── api.py               # FastAPI 路由
│   ├── schemas.py           # 请求/响应 Schema
│   └── websocket.py         # WebSocket 进度推送
├── exceptions.py            # 统一异常体系
└── main.py                  # 应用入口
```

## 12. 可观测性设计

### 12.1 全链路追踪

四级追踪 ID 贯穿全链路：

```
request_id → plan_id → subtask_id → retrieval_call_id
```

所有日志、指标、事件必须携带 `request_id`，子任务级操作额外携带 `subtask_code`。

### 12.2 关键指标埋点

| 指标 | 类型 | 说明 |
|------|------|------|
| `search_task_duration_ms` | Histogram | 全局任务耗时 |
| `subtask_duration_ms` | Histogram | 子任务耗时（按 task_type 分） |
| `subtask_iterations` | Histogram | 子任务纠偏次数 |
| `evidence_eval_score` | Histogram | 证据评估总分分布 |
| `retrieval_latency_ms` | Histogram | 单路检索耗时（按 source_type 分） |
| `llm_tokens_consumed` | Counter | LLM token 消耗 |
| `replan_count` | Counter | 全局重规划次数 |
| `circuit_breaker_open` | Gauge | 熔断器状态（按通道分） |
| `cache_hit_rate` | Gauge | 语义缓存命中率 |

### 12.3 异常告警规则

1. replan_count > 3 → 告警：任务可能陷入循环
2. 某检索通道连续超时 > 5 次 → 告警：通道可能不可用
3. 证据冲突率异常升高（Conflict < 0.7）→ 告警：数据源可能不一致
4. 任务降级率 > 10% → 告警：系统整体质量下降

## 13. API 设计建议

### 13.1 核心接口

```
POST   /api/v1/search                    # 发起检索任务（异步提交，默认 202）
GET    /api/v1/search/{request_id}        # 查询任务状态与结果
DELETE /api/v1/search/{request_id}        # 取消任务
GET    /api/v1/search/{request_id}/trace  # 查询执行轨迹（增强接口，阶段 2）
WS     /api/v1/search/{request_id}/stream # WebSocket 流式进度（可选增强，阶段 2）
```

### 13.2 请求格式

```json
{
  "query": "对比公司2024年Q3和Q4的营收变化，并分析主要原因",
  "session_id": "SES-20260316-001",
  "options": {
    "sla_level": "standard",
    "threshold_profile": "general",
    "max_latency_ms": 120000,
    "max_llm_tokens": 50000
  }
}
```

### 13.3 响应格式

异步提交时，`POST /api/v1/search` 默认返回：

```json
{
  "request_id": "REQ-20260316-a3f1",
  "status": "PENDING",
  "message": "task accepted",
  "poll_url": "/api/v1/search/REQ-20260316-a3f1"
}
```

任务完成后，`GET /api/v1/search/{request_id}` 返回：

```json
{
  "request_id": "REQ-20260316-a3f1",
  "status": "COMPLETED",
  "answer": "Q1华东区销售额达2.3亿元，同比增长21.1%...",
  "confidence": 0.92,
  "citations": [
    {"card_uid": "EC-001", "claim": "...", "source_type": "SQL_DB", "reliability": "T1"}
  ],
  "trace": {
    "plan_versions": 1,
    "subtasks_total": 5,
    "subtasks_completed": 5,
    "total_retrieval_calls": 12,
    "total_llm_tokens": 28000,
    "elapsed_ms": 18000
  }
}
```

### 13.4 补充接口规范

#### 错误响应统一格式

所有 API 错误响应使用统一结构，便于前端统一处理：

```json
{
  "error": {
    "code": "INVALID_QUERY",
    "message": "查询文本不能为空",
    "request_id": "REQ-20260316-a3f1",
    "details": {}
  }
}
```

HTTP 状态码映射：`400` 参数错误、`401` 未认证、`403` 无权限、`404` 任务不存在、`429` 限流、`500` 内部错误、`503` 服务降级。

#### 幂等性

`POST /api/v1/search` 支持 `Idempotency-Key` 请求头，防止网络重试导致重复创建任务：

```
POST /api/v1/search
Idempotency-Key: client-uuid-12345
```

服务端以 `Idempotency-Key` 为 key 在 Redis 中缓存（TTL 24h），重复请求直接返回首次结果。

#### 列表分页接口

```
GET /api/v1/search?page=1&page_size=20&status=COMPLETED&sort=-created_at
```

响应包含分页元数据：`{"items": [...], "total": 100, "page": 1, "page_size": 20}`

#### 健康检查

```
GET /health    # 存活探针（Liveness），只检查进程是否响应
GET /ready     # 就绪探针（Readiness），检查 MySQL + Redis + Celery Broker 连通性
```

`/ready` 返回各依赖状态：`{"mysql": "ok", "redis": "ok", "celery_broker": "ok"}`，任一不可用返回 `503`。

#### Webhook 回调（可选，首版不实现）

```json
{
  "webhook_url": "https://client.example.com/callback",
  "events": ["task.completed", "task.failed", "task.degraded"]
}
```

> 首版默认以轮询查询状态为准，WebSocket 与 Webhook 都作为后续增强能力预留。

### 13.5 安全基线

首版必须覆盖的安全措施，不做会有数据泄露或滥用风险：

1. **密码与密钥管理**：所有密码、API Key、数据库连接串通过环境变量注入（参见 Section 11.1 `AppSettings`），禁止硬编码在代码或配置文件中。`.env` 文件加入 `.gitignore`。

2. **API Rate Limiting**：令牌桶限流，防止单租户耗尽系统资源：
   - 默认：100 req/min/tenant
   - 搜索接口：20 req/min/tenant（每次搜索消耗大量 LLM token）
   - 使用 FastAPI 中间件 + Redis 计数器实现

3. **输入长度限制**：
   - `query` 最大 2000 字符
   - `session_id` 最大 64 字符
   - JSON body 最大 10 KB
   - 超限直接返回 400

4. **Prompt Injection 隔离**：用户输入在拼入 LLM prompt 前，用 XML 标签隔离（`<user_query>...</user_query>`），System Prompt 中明确指示 LLM 不执行用户指令中的系统命令。

5. **租户数据隔离**：
   - Redis Key 统一携带 `tenant_id`：`rag:search:{tenant_id}:task:{task_id}:*`
   - MySQL 查询统一带 `WHERE tenant_id = ?`，通过 Repository 层强制注入
   - 禁止跨租户读取证据卡和任务数据

## 14. 当前仓库可复用经验

### 14.1 MySQL 层

参考：`src/learning_common_lib/mysql_lession/examples/10_fastapi_integration`

复用点：SQLAlchemy 2.x 异步引擎、Repository 模式、Session Factory 生命周期管理。

### 14.2 异常体系

参考：`src/learning_common_lib/python基础/exception教程/templates`

复用点：统一错误码、统一异常基类、对外响应和对内日志字段分离。

### 14.3 异步任务

参考：`src/learning_common_lib/redis_lession/celery教程与Redlock/examples/04_async_worker_tasks`

复用点：按任务类型拆 Worker Lane、Celery prefork 基线、队列路由。

## 15. 实施顺序建议

### 阶段 1：基础骨架

1. 建立目录结构与配置管理
2. 建立枚举、异常体系、数据库连接
3. 建立 SQLAlchemy ORM 模型（search_tasks / task_plans / subtasks / evidence_cards 等）
4. 建立 Port 接口定义 + Mock 实现
5. 建立 Redis 缓存与锁工具

交付标准：模型可初始化，Mock 适配器可独立测试。

测试要求：ORM 模型单测（CRUD 操作、唯一约束、状态枚举）；使用 Alembic 管理数据库迁移，验证迁移脚本可正确执行。

### 阶段 2：全局循环

1. 完成 Planner Service（LLM 调用生成 DAG）
2. 完成 DAG 拓扑排序与 Scheduler
3. 完成 `executor -> Celery -> resume_orchestrator` 的恢复编排链路
4. 完成 StepGate 判定逻辑
5. 完成 GlobalReplan + 循环检测
6. 完成 LoopGuard + Fallback 降级

交付标准：给定一个查询，能生成 DAG、完成 READY 任务抢占，并在 Celery 回写结果后恢复编排继续推进。

测试要求：DAG 调度单测（拓扑排序正确性、入度计算、并发度控制、死锁检测、旧 `plan_version` 结果 fencing）；Replan 循环检测单测（指纹匹配、相似度阈值、边际收益递减）。

### 阶段 3：子任务闭环

1. 完成查询改写层（QV/QK/QS/QG/QW）
2. 完成多路检索执行与证据汇聚
3. 完成证据压缩与原子化
4. 完成三维评估打分
5. 完成缺口诊断与纠偏重试
6. 完成输出三重校验

交付标准：单个子任务能跑完检索-评估-纠偏-校验全流程。

测试要求：子任务集成测试（Mock LLM + Mock 检索通道，验证完整闭环）；证据评估单测（三维打分计算、阈值判定、冲突检测）；错误处理测试（LLM 超时、检索不可用时的降级行为）。

### 阶段 4：记忆与会话

1. 完成 L2 工作记忆 checkpoint
2. 完成 L3 全局证据池共享
3. 完成 L4 会话记忆（滑动窗口+摘要）
4. 预留 L5 语义缓存与用户偏好接口，首版只保留接入点
5. 完成 L1 上下文窗口组装与裁剪

交付标准：多轮对话能正确指代消解，跨子任务能复用证据。

测试要求：记忆集成测试（L2 checkpoint 写入/恢复、L3 跨子任务证据共享、L4 滑动窗口摘要正确性）；Redis 故障回退测试（Redis 不可用时 MySQL 回退路径）。

### 阶段 5：工程化加固

1. 增加多层超时与熔断
2. 增加全链路追踪与指标埋点
3. 增加并发控制与幂等保障
4. 增加 API 层与可选 WebSocket 流式推送
5. 增加测试覆盖

交付标准：关键链路有单测与集成测试，故障场景可复现。

测试要求：端到端测试（从 API 发起请求到返回结果的完整链路）；负载测试基线（使用 locust 或 k6，提交接口目标 `P95 < 200ms`，复杂深搜完成时间记录 `P50/P95` 基线，典型目标 `P95 30-60s`）；故障注入测试（模拟 Redis 宕机、LLM 超时、Worker 崩溃）。

## 16. 首版默认业务决策

1. 首版 L4 会话记忆只实现滑动窗口 + 渐进式摘要，不引入向量检索和知识图谱通道。
2. 首版检索通道只实现向量库 + ES 两路，SQL/图数据库/Web 搜索用 Mock 占位。
3. 首版 DAG 最大并行度限制为 3，最大 replan 次数限制为 2，子任务最大迭代次数限制为 3。
4. 首版异步任务固定采用 Celery + Redis Broker，按 `plan_jobs`、`execute_jobs`、`evaluate_jobs` 拆队列。
5. 首版不实现用户偏好记忆（L5）；语义缓存只保留接口和 Redis 简版占位，不作为首版必收项。
6. 首版降级策略：超限时返回已完成子任务的部分结果 + 不确定性说明 + 下一步建议。
7. 首版 Web 通道用 Mock 实现，WebGuard（Web 内容安全过滤）随 Web 通道后续实现。
8. 并行度限制由 `scheduler_node` 中 `ready[:MAX_CONCURRENT]` 切片和 MySQL 条件抢占共同实现（参见 [codex_技术拆解 Section 2.7](./codex_技术拆解.md#langgraph-dag)）。
9. 首版 ACL 用 `tenant_id` 过滤实现租户隔离，RBAC/ABAC 权限模型延后。
10. `POST /api/v1/search` 首版默认异步提交；`/trace` 与 `WS /stream` 作为增强接口后置实现。

## 17. 我建议在实现阶段优先坚持的几个取舍

1. **优先把 DAG 调度和状态机做对**，这是整个系统的骨架，后续所有功能都依赖它。
2. **优先做证据卡标准化**，全链路以证据卡为数据单元，避免各模块自定义数据格式。
3. **优先做幂等和 checkpoint**，子任务中途崩溃必须能恢复，不能从头重跑。
4. **先跑通最小全局骨架和恢复编排链路，再补齐单子任务闭环细节**，避免后期返工状态模型。
5. **锁策略以简单可解释为主**，大部分场景 Redis 原子操作即可，不要过早引入 Redlock。
6. **先把 Mock 适配器跑顺**，再替换真实 LLM / 向量库 / ES。
