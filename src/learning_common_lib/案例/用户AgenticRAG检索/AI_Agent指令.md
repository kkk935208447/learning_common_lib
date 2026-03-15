## 目标
至少要完成的点:
1. 在 "src/learning_common_lib/案例/用户AgenticRAG检索" 目录下搭建整个AgenticRAG用户deep seacher检索的框架，task状态传递必须高性能高稳定且可控
2. Milvus 与 ES 等服务未启动，你可以封装成一个模块架构，然后用dict或其他对象模拟一下即可
3. 本次代码主要是架构代码，需要梳理撰写完整的数据流向，重点在 agent/ multi agent的搭建，下面有一份目前暂定的技术方案，你可以先参考一下，不合理处可以与我沟通增删
4. 项目目标是中小型企业的并发度。为了考虑k8s后期的扩展(小规模)，你看看如何设计锁(分布式锁 或者 乐观锁)
6. 建议使用面向对象热接口的方式编写代码


## 运行环境
python 3.11，由uv控制版本，uv run xxx.xxx.py
mysql 8.xxx 版本，已经启动docker运行，主机地址:localhost，账户 root，密码123456
redis 7.xxx 版本，已经启动docker运行，主机地址:localhost，账户 default 密码123456

## 参考
仅参考里面的优点，不用照搬里面的代码模式风格

 - 目录"src/learning_common_lib/mysql_lession/examples/10_fastapi_integration" 是 SQLalchemy 操作mysql的参考
 - 目录"src/learning_common_lib/redis_lession/celery教程与Redlock/examples/04_async_worker_tasks" 是 celery 异步参考
 - 目录"src/learning_common_lib/python基础/exception教程/templates" 是 exception 参考


## AgenticRAG 用户检索方案
```text
Agentic RAG 用户检索方案
一、用户复杂任务 Agent 检索  plan-execute-replan  流程图
1. Agentic 检索架构图（multi-agent，plan-execute-replan 计划-检索-纠偏检索）
•	“新一代 Agentic RAG”思路
￮	近期方法普遍强调把战略规划和执行检索解耦（例如 Plan*RAG、HiRA）：计划是外部结构（DAG），执行是可迭代 worker
￮	检索质量问题更适合在局部纠偏（CRAG、Self-RAG、KiRAG）：先重写查询、换检索路由、补源、再评估，不要每次都改全局 DAG
￮	评估也在走细粒度（RAGChecker）：不是“充分/不充分”二值，而是 coverage（覆盖） / conflict （冲突）/ 置信度 / freshness 多维信号

•	核心结论
￮	主循环（Global）负责：任务分解、依赖调度、是否进入下一子任务、是否改主计划。
￮	子循环（Local）负责：该子任务内的检索-评估-纠偏（plan-execute-replan）。
￮	通常当“子任务检索不可局部修复” 或 “已有子任务检索结果与原计划相差太大”会启动 Global Replan。

•	流程图如下：
￮	图1：主流程（简化版，子任务闭环抽象成一个节点）
￮	图2：子任务执行闭环（从主图拆出的详细 loop）
1.1 图1：总规划器 Plan - Execute - RePlan
flowchart TD
        %% 样式定义
        classDef agent fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
        classDef db fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,stroke-dasharray: 5 5;
        classDef process fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
        classDef decision fill:#fffde7,stroke:#fbc02d,stroke-width:2px;
        classDef security fill:#ffebee,stroke:#c62828,stroke-width:2px;
        classDef network fill:#e0f7fa,stroke:#0097a7,stroke-width:2px;
        classDef user fill:#f5f5f5,stroke:#616161,stroke-width:2px;
        classDef transform fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;

        %% 节点定义
        Start(["👤 复杂任务入口<br/>（简单任务走独立接口）"]):::user
        Auth{"🛡️ 身份/租户/ACL 校验"}:::security
        Denied["🚫 无权限/越权告警"]:::security
        Intake["🧾 任务画像<br/>目标/约束/SLA"]:::process

        subgraph ControlPlane["🧭 控制平面（跨层）"]
            Ctrl["统一控制器<br/>Policy + Budget(预算) + <br/>StopRule(停止规则)"]:::security
        end

        subgraph PlanLayer["🧠 复杂任务规划层"]
            Planner["分层规划器<br/>Hierarchical Planner"]:::agent
            DAG["📋 任务清单/有向无环<br/>DAG生成"]:::agent
            StepScheduler["🧩 子任务调度<br/>按DAG依赖选择可执行步骤"]:::process
            Router{"路由决策<br/>并行/串行/工具选择"}:::decision
            StepGate{"🧭 主步骤推进判定<br/>执行下一步/修改原计划/全部完成"}:::decision
            GlobalReplan["🧠 主计划重规划<br/>调整DAG依赖与任务顺序"]:::agent
        end

        SubtaskLoop["🔁 子任务执行闭环<br/>（见图2）"]:::agent
        LoopGuard{"⛔ 迭代守卫<br/>迭代/预算/时延"}:::decision
        Fallback["🧯 安全降级输出<br/>说明不确定性 + 下一步建议"]:::process
        Output(["💬 最终回答<br/>引用 + 置信度"]):::user

        %% 主流程
        Start --> Auth
        Auth -- "拒绝" --> Denied
        Auth -- "通过" --> Intake

        Intake --> Planner
        Planner --> DAG
        DAG --> StepScheduler
        StepScheduler --> Router
        Router --> SubtaskLoop

        SubtaskLoop -- "子任务通过校验" --> StepGate
        SubtaskLoop -- "局部纠偏超限/跨任务冲突" --> GlobalReplan
        SubtaskLoop -- "需用户补充" --> Planner

        StepGate -- "执行下一步" --> StepScheduler
        StepGate -- "修改原计划" --> GlobalReplan
        StepGate -- "全部完成" --> Output

        GlobalReplan --> LoopGuard
        LoopGuard -- "允许" --> Planner
        LoopGuard -- "超限" --> Fallback
        Fallback --> Output

        %% 控制平面约束
        Ctrl -. "策略约束" .-> Planner
        Ctrl -. "预算约束" .-> Router
        Ctrl -. "停止约束" .-> LoopGuard
1.2 图2：子任务 Execute 过程，Single-Agent
%%{init: {'theme': 'default', 'flowchart': {'nodeSpacing': 50, 'rankSpacing': 80, 'curve': 'basis'}}}%%
flowchart TD
      %% 样式定义
      classDef agent fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
      classDef db fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,stroke-dasharray: 5 5;
      classDef process fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
      classDef decision fill:#fffde7,stroke:#fbc02d,stroke-width:2px;
      classDef security fill:#ffebee,stroke:#c62828,stroke-width:2px;
      classDef network fill:#e0f7fa,stroke:#0097a7,stroke-width:2px;
      classDef user fill:#f5f5f5,stroke:#616161,stroke-width:2px;
      classDef transform fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;
      classDef cache fill:#e8eaf6,stroke:#283593,stroke-width:2px;

      Router{"路由决策<br/>并行/串行/工具选择"}:::decision

      %% ===== 查询语义缓存 =====
      subgraph CacheLayer["🗄️ 查询语义缓存（改写前）"]
          CacheProbe{"语义相似度探测<br/>Embedding 余弦 ≥ 阈值？"}:::cache
          CacheHit["✅ 缓存命中<br/>返回历史证据集+候选答案"]:::cache
          CacheWrite["📝 缓存回写<br/>query embedding → 证据集+Claim"]:::cache
      end

      %% 核心修改：为子图标题增加换行符，防止横向拉伸过长
      subgraph RewriteLayer["💡 查询改写与工具准备<br/>和检索前 ACL/tenant filter"]
          direction LR
          QV["语义增强改写<br/>指代消解/HyDE/多查询等"]:::transform
          QK["精准术语提取<br/>术语库对齐"]:::transform
          QS["结构化翻译<br/>Schema Linking/SQL草案等"]:::transform
          QG["图查询规划<br/>实体关系抽取/多跳计划等"]:::transform
          QW["外部检索准备<br/>时效约束/来源策略等"]:::transform
      end

      subgraph ExecLayer["🔍 多路检索执行层"]
          direction LR
          Vec[("内部向量库<br/>Milvus/Pinecone")]:::db
          ES[("全文检索<br/>Elasticsearch")]:::db
          SQL[("关系数据库<br/>PostgreSQL/Hive")]:::db
          KG[("图数据库<br/>Neo4j/GraphRAG")]:::db
          Web[("外部网页<br/>Search API")]:::db
      end

      WebGuard["Web 沙箱<br/>白名单/注入检测/HTML清洗"]:::security
      Merge["📥 证据汇聚<br/>tenant过滤 + 去重"]:::process
      Fusion["🧩 排序融合<br/>RRF/时间衰减权/多路归并"]:::process

      subgraph PostLayer["⚙️ 融合与精炼层"]
          direction LR
          R1["轻量重排<br/>Bi-Encoder"]:::process
          R2["深度重排<br/>Cross-Encoder"]:::process
          Compress["证据压缩与原子化<br/>去噪/去冗余/结构化证据卡"]:::process
      end

      %% ===== 证据评估标准化 =====
      subgraph EvidenceEval["🤔 证据充分性评估（标准化三维打分）"]
          direction TB
          Score_Evidence["📊 Coverage 覆盖性：子任务所需信息点是否都有证据支撑<br/><br/>⚔️ Conflict 冲突性：多源证据是否矛盾/程度量化<br/><br/>🎯 Confidence 置信度：来源可靠性加权（内部库 > Web）"]:::decision
          Aggregate["综合打分<br/>加权公式 → 总分"]:::process
          Threshold{"阈值判定<br/>按业务场景配置<br/>财务类高阈 / 一般咨询低阈"}:::decision
      end

      ParentHydration["📄 父文档按需召回<br/>仅Top-N证据对应父块/邻域/父块去重"]:::process
      DraftClaims["📝 子任务候选答案/Claim集<br/>仅子任务上下文"]:::process
      Verify{"✅ 输出校验<br/>事实一致性/敏感信息/引用对齐"}:::decision

      Retry["🔄 纠偏重规划<br/>按映射改路由/调参数/补检索"]:::agent
      LocalLoopGuard{"⛔ 子任务迭代守卫<br/>迭代/预算/时延"}:::decision
      Escalate["📣 子任务升级报告<br/>局部纠偏无增益/跨任务冲突"]:::agent

      Gap{"缺口类型判定"}:::decision
      GapMap["🗺️ 缺口类型→纠偏动作<br/>术语歧义→QK增强<br/>时效缺口→QW+Web<br/>多跳缺口→QG+KG<br/>数值缺口→QS+SQL"]:::agent
      Clarify["🙋 追问关键缺失信息"]:::user

      SubtaskPass["✅ 子任务通过校验<br/>返回主步骤推进判定"]:::process
      ToGlobal["↩ 返回主计划重规划"]:::agent
      ToPlanner["↩ 返回主规划器"]:::agent

      %% 逻辑连接保持不变
      Router --> CacheProbe
      CacheProbe -- "命中" --> CacheHit
      CacheHit -- "若存在Claims" --> DraftClaims
      CacheHit --> ParentHydration
      CacheProbe -- "未命中" --> RewriteRoute

      RewriteRoute{"改写路由<br/>按Router决策激活对应改写"}:::decision
      RewriteRoute -- "语义推理" --> QV
      RewriteRoute -- "精准术语" --> QK
      RewriteRoute -- "复杂关联" --> QG
      RewriteRoute -- "实时外部" --> QW
      RewriteRoute -- "结构化" --> QS

      QV --> Vec
      QK --> ES
      QS --> SQL
      QG --> KG
      QW --> WebGuard
      WebGuard --> Web

      Vec --> Merge
      ES --> Merge
      SQL --> Merge
      KG --> Merge
      Web --> Merge

      Merge --> Fusion
      Fusion --> R1
      R1 --> R2
      R2 --> Compress

      Compress --> Score_Evidence
      Score_Evidence --> Aggregate
      Aggregate --> Threshold

      Threshold -- "充分（≥阈值）" --> ParentHydration
      ParentHydration --> DraftClaims
      DraftClaims --> Verify
      Verify -- "通过" --> CacheWrite
      CacheWrite --> SubtaskPass
      Verify -- "不通过" --> Retry

      Threshold -- "不充分（<阈值），纠偏检索" --> Gap
      Gap -- "可补检" --> GapMap
      GapMap --> Retry
      Gap -- "需用户补充" --> Clarify

      Retry --> LocalLoopGuard
      LocalLoopGuard -- "允许" --> Router
      LocalLoopGuard -- "超限" --> Escalate

      Escalate --> ToGlobal
      Clarify --> ToPlanner

1.3 节点定义解析
•	Start：进入复杂任务入口并打上 request_id/session_id/tenant_id；原因是后续每次重试都要可追踪；方法是统一网关注入全链路上下文。
•	Auth：做身份、租户、ACL 校验；原因是企业场景首要风险是越权；方法是 RBAC/ABAC + 数据标签 双重约束。
•	Denied：拒绝并告警；原因是安全事件需要审计证据；方法是记录拒绝原因码、策略命中规则、最小必要日志。
•	Intake：构建任务画像（目标、约束、SLA、时效）；原因是不做画像就无法合理规划；方法是规则+LLM分类得到 intent/complexity/risk。
•	Ctrl（跨层）：下发 Policy/Budget/StopRule；原因是避免每层各自为政；方法是把控制参数写入运行态上下文（如 max_iter/max_cost/max_latency）。
•	Planner：把问题拆成子问题与子目标；原因是复杂问题常包含多个事实点；方法是分层规划（主目标->子目标->检索动作）。
•	DAG：生成任务清单与依赖关系；原因是并行与串行要显式化；方法是有向无环图定义 step_id/depends_on/tool_type。
•	Router：为每个子任务选择检索路径；原因是不同问题类型适配不同通道；方法是路由策略（规则优先+轻量模型打分）。
•	QV：语义增强改写（指代消解、HyDE、多查询）；原因是提升召回覆盖；方法是生成 2-5 个互补 query 并去重。
•	QK：精准术语提取；原因是企业术语、别名、缩写很多；方法是术语词典对齐+同义归一+拼写纠错。
•	QS：结构化翻译（Schema Linking、SQL草案）；原因是数值/统计类问题必须走结构化源；方法是受限 SQL 生成+执行前静态检查。
•	QG：图查询规划（实体关系、多跳）；原因是关联链路问题文本检索难覆盖；方法是实体链接+路径约束（跳数、关系白名单）。
•	QW：外部检索准备（时效、来源策略）；原因是内部库可能没有最新信息；方法是限定可信域名、时间窗、搜索深度。
•	WebGuard：外部内容沙箱；原因是网页注入和脏内容风险高；方法是白名单、HTML 清洗、注入模式检测。
•	ExecLayer：多路检索执行（Vec/ES/SQL/KG/Web）；原因是单一检索天然有盲区；方法是并发执行并设置每路超时和预算上限。
•	Merge：证据汇聚（tenant过滤、去重）；原因是跨源结果格式不一且会重复；方法是统一 EvidenceCard 结构并做近重复合并。
•	Fusion：排序融合（RRF/多路归并）；原因是不同通道分数不可直接比较；方法是基于排名位置融合而非原始分数硬拼。
•	R1：轻量重排（Bi-Encoder）；原因是快速筛掉低相关；方法是对 TopK 做语义重排，保留候选池。
•	R2：深度重排（Cross-Encoder）；原因是高精度判断 query-evidence 匹配；方法是对小候选集精排，控制算力成本。
•	Compress：证据压缩与原子化；原因是上下文窗口有限；方法是抽取“原子事实卡”（结论、来源、时间、片段位置）。
•	EvidenceGate：评估证据充分性（覆盖与冲突）；原因是避免证据不足时直接生成答案；方法是计算 coverage/conflict/trust/freshness 综合分。
•	ParentHydration：按需召回父文档及其邻近文档；原因是精排命中常是局部片段，回答要上下文；方法是只回填 TopN 证据对应父块并去重。
•	Verify：输出校验（事实一致性、敏感信息、引用对齐）；原因是最终风险控制在此收口；方法是规则引擎+校验模型双轨。
•	Output：返回子任务回答（引用+置信度）；原因是企业用户需要可核验结果；方法是每条核心结论绑定来源和时间戳。
•	Retry/GaP/GapMap：不足时纠偏重规划；原因是一次检索不可能覆盖全部场景；方法是“缺口类型->补救动作”映射路由。
•	Clarify：需用户补充时追问；原因是关键信息缺失时继续检索只会浪费预算；方法是最小问题集追问（时间范围、对象、口径）。
•	LoopGuard：迭代守卫；原因是防止无限重试；方法是限制 max_iter/max_cost/max_latency 与边际收益阈值。
•	Fallback：超限降级输出；原因是系统要“有边界地失败”；方法是明确不确定性、给出下一步可执行建议。

2. 流程解析
 Plan-and-Execute (先计划后执行)：企业级的主流
这是目前很多中大型企业 Agent 的核心逻辑。它将过程拆分为两个角色：Planner（规划者） 和 Executor（执行者）
￮	工作逻辑：Planner --> Executor -->Re-planner
▪	Planner： 接收问题，一次性生成一个包含 Step 1, Step 2, Step 3 的完整计划列表
▪	Executor： 逐条执行任务，不再每步都问 Planner
▪	Re-planner： 全部执行完或某一步卡住后，再统一汇总进行反思
￮	为什么企业主流？
▪	可预测性： 管理层可以看到 Agent 生成的“计划清单”，如果不合理可以及时干预
▪	并行化： 计划中的 Step 1 和 Step 2 如果互不依赖，可以同时发起检索，大幅降低延迟
▪	稳定性： 减少了频繁调用 LLM 带来的随机性波动
注意：和 React 方式相比，Plan-Execute-RePlaner 具有并发执行任务的能力，并且由于 Re-planner 的存在，它的整体过程也具有动态调整的能力
2.1 总规划的 Plan-Execute-RePlaner（最外层 plan）
DAG 不是传统意义上的 Airflow 离线调度，而是运行时动态生成、动态修改的任务图。每次用户提问，Planner 实时生成一张 DAG，Scheduler 实时消费。

%%{init: {'theme': 'default', 'flowchart': {'nodeSpacing': 70, 'rankSpacing': 30, 'curve': 'basis'}}}%%
flowchart LR
      subgraph Plan-Execute-RePlan 生命周期
          direction LR
          A["用户提问"] --> B["Planner 生成 DAG"]
          B --> C["Scheduler 调度执行"]
          C --> D["StepGate 判定"]
          D -- "需重规划" --> B
          D -- "完成" --> E["汇总输出"]
      end
2.1.1 数据结构设计
•	生产中 DAG 通常用 JSON 描述，核心是节点列表 + 依赖关系。以下是一个实际示例：
用户问题："对比我们公司2024年Q3和Q4的营收变化，并分析主要原因"
JSON
 Planner 生成的 DAG
{
    "plan_id": "plan_20260209_a3f1",
    "query": "对比我们公司2024年Q3和Q4的营收变化，并分析主要原因",
    "tasks": [
      {
        "task_id": "t1",
        "description": "检索2024年Q3营收数据",
        "type": "retrieval",
        "route": ["structured", "keyword"],
        "depends_on": [],
        "priority": 1,
        "timeout_ms": 10000
      },
      {
        "task_id": "t2",
        "description": "检索2024年Q4营收数据",
        "type": "retrieval",
        "route": ["structured", "keyword"],
        "depends_on": [],
        "priority": 1,
        "timeout_ms": 10000
      },
      {
        "task_id": "t3",
        "description": "对比Q3与Q4营收差异，计算变化幅度",
        "type": "reasoning",
        "route": ["reasoning"],
        "depends_on": ["t1", "t2"],
        "priority": 2,
        "timeout_ms": 15000
      },
      {
        "task_id": "t4",
        "description": "检索Q3-Q4期间的重大业务事件、市场变化、政策调整",
        "type": "retrieval",
        "route": ["semantic", "graph"],
        "depends_on": [],
        "priority": 1,
        "timeout_ms": 12000
      },
      {
        "task_id": "t5",
        "description": "综合营收变化与业务事件，归因分析主要原因",
        "type": "reasoning",
        "route": ["reasoning"],
        "depends_on": ["t3", "t4"],
        "priority": 3,
        "timeout_ms": 20000
      }
    ],
    "metadata": {
      "estimated_total_ms": 35000,
      "max_parallel_width": 3,
      "created_at": "2026-02-09T10:30:00Z"
    }
  }
2.1.2 对应的 DAG 图
flowchart LR
      t1["t1: 检索Q3营收"]
      t2["t2: 检索Q4营收"]
      t4["t4: 检索重大业务事件"]
      t3["t3: 对比营收差异"]
      t5["t5: 归因分析"]

      t1 --> t3
      t2 --> t3
      t4 --> t5
      t3 --> t5

      style t1 fill:#e8f5e9,stroke:#2e7d32
      style t2 fill:#e8f5e9,stroke:#2e7d32
      style t4 fill:#e8f5e9,stroke:#2e7d32
      style t3 fill:#fff3e0,stroke:#ef6c00
      style t5 fill:#e3f2fd,stroke:#1565c0
2.1.3 DAG 字段设计要点
字段	作用	生产注意事项
task_id	唯一标识	用于依赖引用、日志追踪、缓存 key
depends_on	前置依赖列表	这是 DAG 的核心，Scheduler 据此判断可执行性
type	任务类型	retrieval / reasoning / reflection(反思)，决定分发给哪个 Executor
route	检索路由提示	建议子任务闭环激活哪些改写和检索通道
priority	拓扑层级	同层内的调度优先级，数字越小越优先
timeout_ms	单任务超时	超时后标记失败，触发降级或重规划
status	运行时状态	pending → running → success / failed / skipped
result	执行结果	完成后填入，供下游依赖任务消费
2.1.4 调度算法：拓扑排序 + 就绪队列：调度器的核心逻辑并不复杂，本质是持续扫描就绪任务并分发执行：
•	并行度控制：ReadyQueue 中可能同时有多个任务就绪，但不能无限并行。通过 max_concurrent 参数限制（通常 3~5），避免 LLM 并发过高导致限流
•	优先级排序：同层就绪任务按 priority 排序，关键路径上的任务优先执行
•	超时处理：单任务超时后标记 failed，其下游任务根据策略决定：跳过（skipped）或触发重规划
•	动态修改：重规划时，Scheduler 需要能热替换 DAG——取消未执行的任务，插入新任务，重新计算入度
flowchart TD
      Start(["DAG 输入"]) --> Init["计算每个节点的入度<br/>in_degree 字典"]
      Init --> SeedQueue["入度=0 的节点<br/>加入就绪队列 ReadyQueue"]
      SeedQueue --> Check{"ReadyQueue<br/>是否为空？"}

      Check -- "非空" --> Dispatch["从 ReadyQueue 取出任务<br/>按 priority 排序<br/>并行提交给 ExecutorPool"]
      Dispatch --> Wait["等待任一任务完成"]
      Wait --> Update["已完成任务的所有下游节点<br/>in_degree -= 1"]
      Update --> NewReady["in_degree 变为 0 的节点<br/>加入 ReadyQueue"]
      NewReady --> Check

      Check -- "空 或 全部完成" --> Done(["调度结束"])
      Check -- "空 或 有未完成" --> Deadlock["死锁/异常检测<br/>触发重规划或降级"]

      style Dispatch fill:#e3f2fd,stroke:#1565c0
      style Deadlock fill:#ffebee,stroke:#c62828
2.1.5 DAG 重规划机制
通常当“子任务检索不可局部修复” 或 “已有子任务检索结果与原计划相差太大”会启动 Global Replan。
重规划是 DAG 区别于静态 Pipeline 的核心能力。核心原则，已完成的任务结果不丢弃。重规划只调整未执行的部分，避免重复消耗。


2.2 子任务执行Execute执行（Single - Agent）
•	核心不是“检索一次”，而是分层解耦：规划、改写、执行、验证 分层并多次执行，便于独立优化和替换组件
•	以“证据”为中心，而不是以“模型直觉”为中心，先找证据再组织答案
•	把复杂问题拆成可执行子任务（可并行任务 + 串行任务），用 DAG 管理依赖与并行，减少遗漏
•	用 Budget + StopRule 把质量、时延、成本变成可控工程指标
•	检索阶段：用 Retry + GapMap + Clarify 处理不确定性，避免一次检索失败就直接胡答，必要时可以向人工需求额外知识
•	生成阶段：通过 Verify ，控制子任务的输出事实一致性（防幻觉）、PII敏感信息、对齐引用（证据点）
2.2.1 子任务 Single - Agent 智能路由决策
借用上文总Plan规划器的建议，选择合适的路由进行检索，ACL过滤、检索证据验证、子任务输出结果验证、触发纠偏补检等
2.2.2 Milvus 向量检索的“重写”的优化策略有哪些
用户上下文指代消解、语义补充、HyDE（伪文档搜索，Answer 搜 Answer）、多查询、Chunk 对齐优化（Query 搜 Query ）
2.2.3 ES 全文检索的“重写”的优化策略有哪些
改写发生在构建 ES Query DSL 之前，目的是将用户的自然语言转化为 ES 能高效匹配的检索表达。以下是六大策略
•	策略一：领域同义词扩展
￮	问题：用户说"辞退"，文档里写的是"解除劳动合同"，ES 默认匹配不上。
￮	方案：维护领域同义词表，改写时自动扩展。
用户输入：  "员工辞退流程"
改写输出：  "员工 (辞退 OR 解除劳动合同 OR 辞退解聘 OR 终止劳动关系) 流程"
同义词表结构示例：
标准术语	同义词	来源
解除劳动合同	辞退，辞退解聘，开除，终止劳动关系	HR术语库
年度绩效考核	年终考核，KPI考核，绩效评估，年度评价	HR术语库
差旅报销	出差报销，商旅报销，差旅费用报销	财务术语库
两种实现路径：
方式	做法	优劣
ES 侧同义词过滤器	在 index 的 analyzer 中配置 synonym_graph filter	索引时扩展，查询无额外开销；但更新同义词需 reindex
查询侧 LLM 扩展	改写层用 LLM/术语表在查询时扩展	灵活，不需要 reindex；但增加查询延迟
•	策略二：术语对齐与纠偏
￮	问题：用户用口语化表达，与文档中的正式术语不匹配。
用户输入：  "五险一金怎么交"
术语对齐：  "社会保险 AND 住房公积金 AND (缴纳 OR 缴费 OR 申报)"
实现方式：维护一个术语标准化映射表，改写时做查表替换，如：
五险一金        →  社会保险, 住房公积金
  打卡               →  考勤签到
  请假条           →  请假申请单
  涨工资           →  薪资调整
•	策略三：查询结构化拆分
￮	问题：用户的复合查询直接丢给 ES，召回率低。
用户输入：  "入职不满一年的员工能不能休年假"，直接搜这句话，ES 很难精准匹配。件：
改写时拆分为结构化条，如拆分结果：
    ├── 核心实体：年假 / 年休假
    ├── 约束条件：入职时间 < 1年
    └── 查询意图：资格判定（能不能）
  构建的 ES Query：
    must:   ["年假 OR 年休假"]
    should: ["入职", "工龄", "工作年限", "未满一年"]
    filter: [文档类型 = "制度规定"]
flowchart LR
      Input["复合查询"] --> Extract["LLM 提取<br/>实体 + 条件 + 意图"]
      Extract --> Core["核心实体<br/>→ must 子句"]
      Extract --> Constraint["约束条件<br/>→ should 子句（boost）"]
      Extract --> Intent["查询意图<br/>→ filter 子句"]
      Core --> DSL["组合 ES Query DSL"]
      Constraint --> DSL
      Intent --> DSL
•	策略四：多查询扩展（Multi-Query）
￮	问题：单一查询角度有盲区，召回不全。
￮	方案：从不同角度生成 2~3 个变体查询，分别检索后合并去重。
原始查询：  "员工出差期间发生工伤怎么处理"
扩展查询：
    Q1（制度角度）：  "差旅期间工伤认定流程及报销标准"
    Q2（法规角度）：  "出差工伤 劳动法 工伤保险条例"
    Q3（操作角度）：  "员工出差受伤 HR处理步骤 报案材料"
注意：变体数量控制在 2~3 个，过多会增加 ES 压力和延迟。每个变体的 size 可以适当缩小（比如各取 top 5 而非 top 10）
•	策略五：时间感知改写

2.2.4 ACL 验证与filter是如何做的
ACL 安全护栏有两道，具体见上文 图1 与 图2
	第一道：入口验证	第二道：检索过滤
时机	请求进入系统时	每次检索执行时
粒度	用户/角色/功能级	文档/行/字段级
问题	"你能不能用这个系统"	"你能不能看到这条数据"
失败结果	直接拒绝，不进入管道	进入管道但过滤掉无权数据
2.2.5 (context)证据压缩与原子化是如何做的，数据格式是怎样的
详情见 图2 (context)证据压缩与原子化
实例场景：
￮	用户查询：「公司Q1季度华东区销售额同比变化多少？主要原因是什么？下季度预测如何？」
￮	任务分解后的子任务：「查询Q1华东区销售额同比变化及归因」
￮	多路检索返回的原始证据（假设5条），如下
编号	来源	内容摘要
E1	SQL/数仓	Q1华东区销售额2.3亿，去年同期1.9亿，同比+21.1%
E2	向量库/周报	"华东区Q1表现亮眼，新客户拓展带动增长超20%"
E3	知识图谱	华东区→新签客户32家（去年同期18家），大客户A续约金额+40%
E4	ES/全文	"华东区Q1销售额约2.1亿，增长约15%"（来源：某部门月度简报，1月数据）
E5	Web/行业报告	"2025Q1华东区消费电子市场整体增速12%"
证据压缩与原子化（Compress）
目标：将多路检索返回的冗长、重叠、含噪声的文档片段，转化为结构化的「证据卡」，供后续打分和生成使用。
•	Step 1：去噪（Noise Filtering）
￮	做什么：采用抽取式过滤与子任务无关的内容。每条证据可能来自长文档，其中只有部分句子与当前子任务相关。
￮	方法：
▪	用 Cross-Encoder（如 bge-reranker-v2-m3 或 ms-marco-MiniLM-L6）对每条证据中的每个句子与子任务 query 做相关性打分
▪	阈值过滤：relevance < 0.3 的句子丢弃
▪	这一步在 PostLayer 的 R2（深度重排）之后执行，复用重排分数
￮	例如：E2 原文可能有3段，其中1段讲团建活动 → 丢弃，只保留销售相关句子。
￮	模型：Cross-Encoder reranker（~100ms/条，批量推理）
•	 Step 2：去冗余（Deduplication）
￮	做什么：合并语义重复的证据片段，保留信息量最大的版本。
￮	方法：
▪	对去噪后的句子做 Embedding 聚类（用 text-embedding-3-large 或 bge-m3）
▪	同一聚类内（余弦相似度 ≥ 0.85）取信息密度最高的句子（优先保留含具体数字/实体的版本）
▪	记录被合并的来源，用于后续多源佐证
￮	例如：
▪	E1 说「同比+21.1%」，E2 说「增长超20%」→ 语义聚类到一起，保留 E1（精确数字），标注 E2 为佐证来源
▪	E4 说「增长约15%」→ 与 E1 不合并（数值冲突），保留为独立证据，标记冲突
￮	模型：Embedding model（已有，复用检索阶段的向量）
•	Step 3：原子化拆分（Atomization）
￮	做什么：将每条证据拆分为不可再分的「原子事实」（Atomic Claim），每个 claim 只表达一个独立的事实断言。
￮	方法：用 LLM 做 claim extraction，prompt 如下：
Plain Text
你是证据分析专家。请将以下文本拆分为独立的原子事实（Atomic Claims）。
每个 claim 必须：
1. 只包含一个独立可验证的事实断言
2. 包含完整的主语、谓语、宾语，脱离上下文也能理解
3. 保留原始数字和时间限定

文本：{evidence_text}
来源：{source_id}

输出 JSON 数组：[{"claim": "...", "type": "数值型|因果型|描述型|时间型", "entities": [...]}]
￮	例如：E3 拆分为
JSON
[
  {"claim": "华东区Q1新签客户32家", "type": "数值型", "entities": ["华东区", "Q1"]},
  {"claim": "华东区去年同期新签客户18家", "type": "数值型", "entities": ["华东区", "去年Q1"]},
  {"claim": "大客户A续约金额同比增长40%", "type": "数值型", "entities": ["大客户A", "续约"]}
]
￮	模型：GPT-4o / DeepSeek-V3（需要较强的指令遵循能力，小模型容易遗漏或合并 claim）
•	Step 4：结构化证据卡生成
￮	做什么：将原子 claim 封装为标准化的证据卡，附带元数据，供后续所有环节消费
￮	证据卡 Schema：
JSON
{
  "card_id": "EC-001",
  "claim": "Q1华东区销售额2.3亿，同比增长21.1%",
  "claim_type": "数值型",
  "source": {
    "source_id": "E1",
    "source_type": "SQL/数仓",
    "reliability_tier": "T1",       // T1=权威系统, T2=内部文档, T3=外部
    "data_freshness": "2025-04-02", // 数据截止日期
    "retrieval_score": 0.92         // 重排分数
  },
  "entities": ["华东区", "Q1", "销售额"],
  "corroborated_by": ["E2"],        // 被哪些其他来源佐证
  "conflicts_with": ["EC-004"],     // 与哪些证据卡冲突
  "confidence": 0.95                // 单卡置信度（来源可靠性 × 重排分数）
}
￮	本例最终产出的证据卡集合
Card ID	Claim	Type	Source Tier	冲突
EC-001	Q1华东区销售额2.3亿，同比+21.1%	数值型	T1(数仓)	EC-004
EC-002	新客户拓展是增长主因	因果型	T2(周报)	—
EC-003	华东区Q1新签客户32家（去年18家）	数值型	T1(图谱)	—
EC-004	华东区Q1销售额约2.1亿，增长约15%	数值型	T2(月度简报,1月)	EC-001
EC-005	大客户A续约金额同比+40%	数值型	T1(图谱)	—
EC-006	华东区消费电子市场整体增速12%	描述型	T3(Web)	—
2.2.6 (context)证据充分性评估的三个指标是如何计算的，用什么方式
详情见 图2 (context)证据充分性评估
证据充分性评估（EvidenceEval）
•	维度一：Coverage（覆盖性）
￮	做什么：检查子任务所需的信息点是否都有证据支撑
￮	方法：
▪	用 LLM 从子任务问题中提取「必需信息点」（Required Information Points, RIPs）
▪	逐一检查每个 RIP 是否被至少一张证据卡覆盖
￮	实例：
Plain Text
子任务：查询Q1华东区销售额同比变化及归因

提取的 RIPs：
  ✅ RIP-1: Q1华东区销售额绝对值 → EC-001 覆盖
  ✅ RIP-2: 去年同期销售额（用于计算同比）→ EC-001 覆盖
  ✅ RIP-3: 同比变化率 → EC-001 覆盖
  ✅ RIP-4: 变化的主要原因/归因 → EC-002, EC-003, EC-005 覆盖
  ❌ RIP-5: 下季度预测 → 无证据覆盖（注：此RIP属于另一子任务，此处不计）

Coverage = 已覆盖RIP数 / 总RIP数 = 4/4 = 1.0
￮	模型：GPT-4o-mini / DeepSeek-V3（RIP 提取是轻量任务，不需要最强模型）
•	维度二：Conflict（冲突性）
￮	做什么：检测多源证据之间的矛盾，量化冲突程度。
￮	方法：
▪	对同一 RIP 下的多张证据卡做成对矛盾检测
▪	数值型 claim：直接比较数值偏差率
▪	因果型/描述型 claim：用 NLI 模型（Natural Language Inference）判断 entailment / contradiction / neutral
Plain Text
冲突检测：
  EC-001 vs EC-004：
    - EC-001: 销售额2.3亿, +21.1%（来源：数仓，T1，数据完整）
    - EC-004: 销售额2.1亿, +15%（来源：月度简报，T2，仅1月数据）
    - 数值偏差：金额差9.5%，增速差6个百分点
    - 冲突原因推断：EC-004 仅含1月数据，非完整Q1 → 标记为"时间范围不一致"
    - 冲突严重度：MEDIUM（可解释的偏差，非根本矛盾）

Conflict Score = 1 - (严重冲突数 × 1.0 + 中等冲突数 × 0.3) / 总证据对数
             = 1 - (0 × 1.0 + 1 × 0.3) / 10 = 0.97
￮	模型：NLI 模型（如 deberta-v3-large-mnli，~50ms/对）或 或者轻量级 LLM，如GPT-4o-mini
•	维度三：Confidence（置信度）
￮	做什么：基于来源可靠性加权，计算证据集的整体可信度。
￮	方法：
Plain Text
来源可靠性权重：
  T1（权威系统：数仓/ERP/图谱）= 1.0
  T2（内部文档：周报/简报/Wiki）= 0.7
  T3（外部来源：Web/行业报告）  = 0.4

单卡置信度 = reliability_tier_weight × retrieval_score × freshness_decay

  EC-001: 1.0 × 0.92 × 1.0 = 0.92  （数仓，最新）
  EC-002: 0.7 × 0.88 × 1.0 = 0.62
  EC-003: 1.0 × 0.85 × 1.0 = 0.85
  EC-004: 0.7 × 0.78 × 0.8 = 0.44  （1月数据，freshness衰减）
  EC-005: 1.0 × 0.82 × 1.0 = 0.82
  EC-006: 0.4 × 0.75 × 0.9 = 0.27

Confidence = Σ(top-K卡置信度) / K  （取与RIP对齐的top卡）
           = (0.92 + 0.85 + 0.82 + 0.62) / 4 = 0.80

freshness_decay 函数：max(0.5, 1 - (当前日期 - 数据日期).days / 365)

•	综合打分与阈值判定
Plain Text
总分 = w1 × Coverage + w2 × Conflict + w3 × Confidence

业务场景权重配置：
  财务/合规类（高精度）：w1=0.4, w2=0.35, w3=0.25, 阈值=0.85
  一般业务咨询：       w1=0.4, w2=0.25, w3=0.35, 阈值=0.70
  探索性分析：         w1=0.5, w2=0.15, w3=0.35, 阈值=0.60

本例（一般业务咨询）：
  总分 = 0.4 × 1.0 + 0.25 × 0.97 + 0.35 × 0.80
       = 0.40 + 0.24 + 0.28 = 0.92

  0.92 ≥ 0.70 → ✅ 充分，进入下一阶段
如果不充分（< 阈值），进入缺口判定：
￮	Coverage 低 → 缺信息点 → 按 GapMap 补检索
￮	Conflict 低 → 严重矛盾 → 追加权威源验证或追问用户
￮	Confidence 低 → 来源不可靠 → 切换到更权威的检索通道

2.2.7 (output)子任务输出结果验证
每一个子任务的context证据原子化并通过验证（覆盖率和冲突率）后，子任务的输出也需要验证（事实一致性[防止幻觉]、PII敏感数据、引用对齐[回答的内容引用的证据文档块是否正确]）

Plain Text
上文mermaid 输出验证片段（见图2）
ParentHydration["📄 父文档按需召回<br/>仅Top-N证据对应父块/邻域/父块去重"]:::process
DraftClaims["📝 子任务候选答案/Claim集<br/>仅子任务上下文"]:::process
Verify{"✅ 输出校验<br/>事实一致性/敏感信息/引用对齐"}:::decision

这三个模块的作用详细说明，并解释该如何计算，数据格式
证据充分后，LLM 基于证据卡集合生成子任务候选答案（DraftClaims），然后进入三重校验。
•	假设生成的候选伪答案为：「Q1华东区销售额达2.3亿元，同比增长21.1%。增长主要由新客户拓展驱动（新签32家，同比增长78%），同时大客户A续约金额增长40%也有显著贡献。行业整体增速约12%，公司表现显著优于市场。」
•	step1：校验一：事实一致性（Factual Consistency）
￮	做什么：检查生成文本中的每个事实断言 claims 是否都能在证据卡中找到支撑，防止幻觉
￮	方法：
▪	对生成文本做 claim extraction（同原子化步骤）
▪	每个 output 断言 claim 与证据卡集合做 NLI 蕴含检测
▪	标记三种状态：SUPPORTED（有证据支撑）/ NOT_SUPPORTED（无证据）/ CONTRADICTED（与证据矛盾）
Plain Text
Output Claims 校验：
  ✅ "Q1华东区销售额达2.3亿元" → SUPPORTED by EC-001
  ✅ "同比增长21.1%" → SUPPORTED by EC-001
  ✅ "新签32家" → SUPPORTED by EC-003
  ✅ "同比增长78%" → SUPPORTED（32/18-1=77.8%≈78%，数学推导合理）
  ✅ "大客户A续约金额增长40%" → SUPPORTED by EC-005
  ✅ "行业整体增速约12%" → SUPPORTED by EC-006
  ✅ "公司表现显著优于市场" → SUPPORTED（21.1% vs 12%，推理合理）

一致性分数 = SUPPORTED数 / 总claim数 = 7/7 = 1.0
阈值：≥ 0.9 通过（允许少量合理推理）
￮	模型：
▪	Claim extraction：GPT-4o-mini
▪	NLI 检测：deberta-v3-large-mnli（轻量快速）或 GPT-4o-mini（更灵活，能处理数学推导）
▪	生产建议：两者级联——先用 NLI 模型快筛，uncertain 的再用 LLM 复核
•	step2：校验二：敏感信息检测（Sensitive Information Filter）
￮	做什么：防止输出中泄露不应暴露的信息（个人隐私、商业机密细节、未公开财务数据等）和 web 搜索有害内容（涉政、涉黄等）
￮	方法：
▪	规则层（快速，无 LLM 开销）：
•	正则匹配：身份证号、手机号、银行卡号、邮箱等 PII 模式
•	关键词黑名单：「机密」「内部」「未公开」等标记
•	ACL 回查：输出中涉及的实体是否在当前用户的权限范围内
▪	模型层（兜底）：
•	用 LLM 做分类：「以下文本是否包含不应对外披露的敏感商业信息？」
•	仅对规则层未拦截的内容执行
模型：规则引擎 + GPT-4o-mini（兜底分类）
Plain Text
本例检测：
  ✅ 无 PII 模式匹配
  ⚠️ "大客户A" → ACL检查 → 当前用户有华东区销售数据权限 → 通过
  ✅ 销售额数据 → 用户角色为销售总监，有权查看 → 通过
•	step3：校验三：引用对齐（Citation Alignment）
￮	做什么：两个方面，① 确保输出中的每个断言 claim 都标注了来源（覆盖率） ②标注的来源确实支持该断言claim （准确率）
￮	方法：
▪	要求生成阶段在每个关键信息断言 claim 后需要标注，如 [EC-xxx]
▪	校验时检查：
•	每个断言是否有引用标注（完整性）
•	标注的证据卡是否真的支持该断言（准确性）
•	是否存在「张冠李戴」（引用了不相关的证据卡）
Plain Text
引用对齐检查：
  "销售额达2.3亿元，同比增长21.1%[EC-001]" → EC-001确实包含此数据 ✅
  "新签32家[EC-003]" → EC-003确实包含此数据 ✅
  "行业整体增速约12%[EC-006]" → EC-006确实包含此数据 ✅

引用覆盖率 = 有引用的断言数 / 总断言数
引用准确率 = 引用正确的断言数 / 有引用的断言数
两者均需 ≥ 0.95
￮	模型：规则匹配 + GPT-4o-mini（语义级别的引用验证）
Plain Text
  校验结果汇总与决策
┌─────────────────┬────────┬────────┬────────┐
│ 校验维度         │ 得分   │ 阈值   │ 结果   │
├─────────────────┼────────┼────────┼────────┤
│ 事实一致性       │ 1.00   │ ≥0.90  │ ✅ PASS │
│ 敏感信息         │ 0 hit  │ 0 hit  │ ✅ PASS │
│ 引用覆盖率       │ 1.00   │ ≥0.95  │ ✅ PASS │
│ 引用准确率       │ 1.00   │ ≥0.95  │ ✅ PASS │
└─────────────────┴────────┴────────┴────────┘

→ 全部通过 → 缓存回写 → 返回主流程

如果不通过：
- 事实一致性不通过 → 回到 Retry，标记 `NOT_SUPPORTED` 的 claim，要求 LLM 重新生成时删除或补充证据
- 敏感信息命中 → 自动脱敏或降级输出
- 引用不对齐 → 回到生成阶段，强制 LLM 重新标注引用
```

```
RAG中超长记忆对话管理方案
记忆管理需要解决四个核心问题：跨 Agent 状态共享、上下文窗口不爆炸、任务状态持久化、经验复用。以下按你的架构层次，从底到顶逐层展开
一、记忆分层总览
参考最新研究（BMAM 的四类记忆、TME 的任务记忆树、H-MEM 的分层记忆），你的架构需要五层记忆：
Plain Text
┌───────────────────────────────────────────┐
│  L5  跨会话长期记忆（Long-Term / Semantic Memory）              │
│      用户画像、历史偏好、领域知识沉淀、语义检索缓存（Semantics cache）         │
│      存储：PostgreSQL + 向量库 + Redis（Semantics cache）         │   
│      生命周期：永久/TTL淘汰                                      │
├──────────────────────────────────────────┤
│  L4  会话级情景记忆（Session / Episodic Memory）                 │
│      本次对话的完整交互轨迹、已完成子任务的摘要                   │
│      存储：Redis + PostgreSQL + 向量库 + 图存储                  │
│      生命周期：会话结束后或者 Redis 缓存超过一定时间后归档                                    │
├──────────────────────────────────────────┤
│  L3  任务级状态记忆（Task State Memory）                         │
│      DAG 执行状态、子任务依赖、全局证据池、预算消耗               │
│      存储：Redis Hash/Stream      生命周期：任务完成后归档        │
├──────────────────────────────────────────┤
│  L2  子任务级工作记忆（Working Memory / Scratchpad）             │
│      当前子任务的证据卡、中间推理、纠偏历史                       │
│      存储：内存 + Redis           生命周期：子任务完成后压缩上提   │
├───────────────────────────────────────────┤
│  L1  Agent 上下文窗口（Context Window）                          │
│      当前 LLM 调用的 prompt，经过裁剪和压缩                      │
│      存储：内存（prompt拼接）      生命周期：单次 LLM 调用         │
└───────────────────────────────────────────┘
二、各层详细设计
Plain Text
跨层数据流动
用户提问
  │
  ▼
[L4 读取] 会话历史 → 指代消解 → 完整 query
  │
  ▼
[L5 读取] 用户偏好 + 程序性记忆 → 影响 Planner 和 Router
  │
  ▼
Planner 生成 DAG → [L3 写入] 任务状态初始化
  │
  ▼
StepScheduler → [L3 读取] DAG 依赖 → 选择可执行子任务
  │
  ▼
Router → [L5 读取] 语义缓存探测
  │    ├─ 命中 → [L2 写入] 直接注入证据卡
  │    └─ 未命中 → 走检索流程
  │
  ▼
子任务执行闭环：
  │  [L2 读写] Scratchpad（证据卡、评估历史、纠偏记录）
  │  [L1 组装] 从 L2/L3/L4 裁剪出最小上下文 → LLM 调用
  │
  ▼
子任务完成：
  │  [L2 → L3] 压缩摘要上提到任务状态
  │  [L2 → L3] 证据卡写入全局证据池
  │  [L2 → L5] 验证通过的结果写入语义缓存
  │
  ▼
StepGate → [L3 读取] 检查所有子任务状态
  │  ├─ 全部完成 → 汇总输出
  │  └─ 继续 → 回到 StepScheduler
  │
  ▼
任务完成：
  │  [L3 → L5] 路由策略效果写入程序性记忆
  │  [L4 写入] 本轮摘要追加到会话历史
  │  [L3
  │  [L3 → PostgreSQL] 任务全量归档
  │  [L4 → L5] 更新用户偏好（查询模式频率等）
1. Agent 上下文窗口管理
问题：Anthropic 的工程团队发现，多 Agent 系统的 token 消耗是单 Agent 的 3-10 倍，主要原因是跨 Agent 重复传递上下文。
核心原则：每个 Agent 只看到它需要的最小上下文，而非全量历史。
上下文窗口的组装策略（以你的子任务闭环中的 LLM 调用为例）：
Plain Text
┌── Agent Context Window（≤ 8K tokens 目标）───────────┐
│                                                              │
│  [System Prompt]  ~500 tokens                                │
│    角色定义 + 输出格式约束                                    │
│                                                              │
│  [Task Brief]  ~300 tokens                                   │
│    从 L3 提取：当前子任务描述 + 约束 + 已知依赖结果           │
│    ← 不是完整 DAG，只是当前子任务需要知道的                   │
│                                                              │
│  [Evidence Cards]  ~3000 tokens                              │
│    从 L2 提取：Top-K 证据卡（结构化 JSON）                    │
│    ← 不是原始文档，是压缩后的证据卡                           │
│                                                              │
│  [Iteration Context]  ~500 tokens                            │
│    从 L2 提取：如果是纠偏重试，附带上轮失败原因和缺口诊断     │
│    ← 只有重试时才注入，首次执行为空                           │
│                                                              │
│  [Conversation Summary]  ~500 tokens                         │
│    从 L4 提取：之前轮次的压缩摘要（非原始对话）               │
│                                                              │
│  [User Query]  ~200 tokens                                   │
│    原始查询 + 改写后的查询                                    │
│                                                              │
└─────────────────────────────────────┘
关键技术：
技术	做什么	怎么做
渐进式摘要	对话历史超过阈值时压缩	每 N 轮用 LLM 生成摘要替换原始消息
证据卡替代原文	不传原始文档 chunk	用第一阶段的结构化证据卡（~100 tokens/卡 vs 原文 ~500 tokens/chunk）
选择性注入	不同 Agent 看不同上下文	Planner 看 DAG + 全局摘要；Executor 看证据卡 + 子任务描述
Token 预算分配	硬性控制各区块上限	超出时按优先级截断：先砍 Conversation Summary，再砍低分证据卡
2. 子任务级工作记忆（Scratchpad）
对应架构中的 图2 整个子任务闭环内部的状态
数据结构
JSON
{
  "subtask_id": "ST-003",
  "subtask_desc": "查询Q1华东区销售额同比变化及归因",
  "iteration": 2,
  "max_iterations": 3,

  "evidence_pool": {
    "cards": [
      {"card_id": "EC-001", "claim": "...", "confidence": 0.92, "source_tier": "T1"},
      {"card_id": "EC-003", "claim": "...", "confidence": 0.85, "source_tier": "T1"}
    ],
    "total_cards": 6,
    "injected_to_context": ["EC-001", "EC-003", "EC-005"]
  },

  "eval_history": [
    {
      "iteration": 1,
      "coverage": 0.75,
      "conflict": 0.97,
      "confidence": 0.80,
      "total_score": 0.82,
      "verdict": "insufficient",
      "gap_type": "coverage_gap",
      "gap_detail": "RIP-4(归因)缺少具体客户数据",
      "action_taken": "QG+KG补检索新签客户关系"
    }
  ],

  "draft_claims": null,
  "verify_result": null,

  "budget_consumed": {
    "llm_tokens": 4200,
    "retrieval_calls": 3,
    "latency_ms": 2800
  }
}
生命周期管理
JSON
子任务开始 → 创建 Scratchpad（内存）
  ↓
每轮迭代 → 追加 eval_history，更新 evidence_pool
  ↓
子任务完成 → 压缩为摘要，上提到 L3（任务状态）和 L4（情景记忆）
  ↓
压缩后的摘要格式：
{
  "subtask_id": "ST-003",
  "status": "completed",
  "iterations_used": 2,
  "final_score": 0.92,
  "key_findings": "Q1华东区销售额2.3亿，同比+21.1%，主因新客户拓展",
  "evidence_refs": ["EC-001", "EC-003", "EC-005"],
  "claim_count": 7,
  "all_claims_supported": true
}
存储选择：
￮	执行中：内存（Python dict / LangGraph State）
￮	持久化备份：Redis Hash（key = subtask:{task_id}:{subtask_id}），防止进程崩溃丢失
￮	完成后：压缩摘要写入 PostgreSQL
3. 任务级状态记忆
对应架构中的：图1 的 DAG、StepScheduler、StepGate、GlobalReplan。这是整个记忆系统的核心枢纽——所有 Agent 通过读写 L3 来协调，而不是直接互传上下文。这就是经典的 Blackboard 模式。
数据结构：
JSON
{
  "task_id": "TASK-20250210-001",
  "user_id": "U-1234",
  "tenant_id": "T-ACME",
  "created_at": "2025-02-10T10:30:00Z",

  "original_query": "公司Q1季度华东区销售额同比变化多少？主要原因是什么？下季度预测如何？",

  "plan": {
    "version": 2,
    "dag": {
      "ST-001": {"desc": "查询Q1华东区销售额同比", "deps": [], "status": "completed"},
      "ST-002": {"desc": "归因分析", "deps": ["ST-001"], "status": "completed"},
      "ST-003": {"desc": "下季度预测", "deps": ["ST-001", "ST-002"], "status": "in_progress"}
    },
    "replan_history": [
      {
        "version": 1,
        "change": "原计划ST-001和ST-002合并为一个子任务",
        "reason": "ST-001执行中发现归因数据与销售额数据来自同一检索路径",
        "timestamp": "2025-02-10T10:32:15Z"
      }
    ]
  },

  "global_evidence_pool": {
    "EC-001": {"claim": "Q1华东区销售额2.3亿，同比+21.1%", "produced_by": "ST-001", "consumed_by": ["ST-002", "ST-003"]},
    "EC-003": {"claim": "新签客户32家", "produced_by": "ST-001", "consumed_by": ["ST-002"]}
  },

  "subtask_summaries": {
    "ST-001": {"status": "completed", "key_findings": "...", "score": 0.92},
    "ST-002": {"status": "completed", "key_findings": "...", "score": 0.88}
  },

  "budget": {
    "total_llm_tokens": 50000,
    "used_llm_tokens": 28000,
    "total_retrieval_calls": 20,
    "used_retrieval_calls": 12,
    "max_latency_ms": 30000,
    "elapsed_ms": 18000,
    "max_iterations": 5,
    "used_iterations": 2
  },

  "control_signals": {
    "policy": "business_query",
    "threshold_profile": "general",
    "stop_reason": null
  }
}
关键设计点：
￮	全局证据池（Global Evidence Pool）
▪	子任务之间共享证据的机制。当 ST-001 产出了 EC-001，ST-003 可以直接引用，不需要重新检索。
Plain Text
ST-001 完成 → 将证据卡写入 global_evidence_pool
ST-003 开始 → 先从 global_evidence_pool 中检查是否有可复用的证据
             → 有 → 直接注入 L2 的 evidence_pool，跳过检索
             → 无 → 正常走检索流程
▪	这解决了 Anthropic 指出的 3-10x token 浪费问题——证据只检索一次，通过 L3 共享。
￮	DAG 状态机
Plain Text
pending → in_progress → completed
             ↓
           failed → (触发 GlobalReplan)
             ↓
           skipped → (被 replan 移除)
▪	每次状态变更写入 Redis Stream，StepScheduler 订阅 Stream 来决定下一步调度
￮	Replan 版本控制
▪	每次 GlobalReplan 生成新的 DAG 版本，保留历史版本。这样 LoopGuard 可以检测"是否在反复 replan 同一个问题"（循环检测）。
存储选择：
￮	Redis Hash：task:{task_id} → 整个 JSON（热数据，读写频繁）
￮	Redis Stream：task:{task_id}:events → 状态变更事件流（用于调度和审计）
￮	PostgreSQL：任务完成后全量归档（冷数据）
4. 会话级情景记忆
原因：用户可能在一个会话中问多个相关问题，后续问题依赖前面的上下文
单一的滑动窗口或摘要压缩无法同时满足"精确回忆"和"全局理解"的需求，因此采用四通道混合架构，每个通道解决不同类型的记忆召回问题。
graph TD
    %% 样式定义
    classDef base fill:#2e2e42,stroke:#dcb,stroke-width:2px,color:#fff,rx:5,ry:5;
    classDef label fill:none,stroke:none,color:#dcb,font-weight:bold;
    classDef container fill:#3b3b55,stroke:#dcb,stroke-width:2px,color:#fff;

    %% 顶部输入
    Start[用户新 query 进入]:::base

    %% L4 混合记忆管理器 容器
    subgraph L4_Manager [L4 混合记忆管理器]
        direction TB
        
        %% 分流点（隐形节点辅助布局）
        Split(( )):::label

        %% 通道 A
        subgraph Channel_A [通道A]
            direction TB
            A1[滑动窗口]:::base
            A2[最近N轮原文]:::base
            A1 --> A2
        end

        %% 通道 B
        subgraph Channel_B [通道B]
            direction TB
            B1[摘要压缩]:::base
            B2[全局语义浓缩]:::base
            B1 --> B2
        end

        %% 通道 C
        subgraph Channel_C [通道C]
            direction TB
            C1[向量检索]:::base
            C2[语义相关<br/>历史片段]:::base
            C1 --> C2
        end

        %% 通道 D
        subgraph Channel_D [通道D]
            direction TB
            D1[知识图谱]:::base
            D2[实体关系<br/>追踪]:::base
            D1 --> D2
        end

        %% 融合部分
        Fuser[混合召回融合器]:::base
        Process[去重 + 排序 + Token预算裁剪]:::base
    end

    %% 底部输出
    End[注入 L1 上下文窗口]:::base

    %% 连接关系
    Start --> Split
    Split --> Channel_A
    Split --> Channel_B
    Split --> Channel_C
    Split --> Channel_D

    A2 --> Fuser
    B2 --> Fuser
    C2 --> Fuser
    D2 --> Fuser

    Fuser --> Process
    Process --> End

    %% 容器样式应用
    class L4_Manager container
    class Channel_A,Channel_B,Channel_C,Channel_D container
以滑动窗口 + 历史摘要的角度来说明，数据结构如下：
JSON
{
  "session_id": "SES-20250210-001",
  "user_id": "U-1234",
  "turns": [
    {
      "turn_id": 1,
      "query": "公司Q1季度华东区销售额同比变化多少？",
      "task_id": "TASK-001",
      "summary": "Q1华东区销售额2.3亿，同比+21.1%，主因新客户拓展(32家)和大客户A续约(+40%)",
      "key_entities": ["华东区", "Q1", "销售额", "大客户A"],
      "timestamp": "2025-02-10T10:35:00Z"
    },
    {
      "turn_id": 2,
      "query": "那华北区呢？",
      "resolved_query": "公司Q1季度华北区销售额同比变化多少？主要原因是什么？",
      "task_id": "TASK-002",
      "summary": "...",
      "key_entities": ["华北区", "Q1", "销售额"],
      "timestamp": "2025-02-10T10:36:30Z"
    }
  ],
  "session_context": {
    "topic": "Q1区域销售分析",
    "mentioned_entities": ["华东区", "华北区", "Q1", "大客户A"],
    "user_intent_pattern": "区域对比分析"
  }
}
以下是根据图片内容提取的 Markdown 格式文本：
机制	作用	实现
指代消解补全语义	"那华北区呢？" → 补全完整查询	将 session_context 注入 QV（语义增强改写）的 prompt
实体追踪	跨轮次维护提到的重要实体事件，防止摘要造成的信息损失	每轮提取 key_entities，合并到 session_context
存储选择：
•	Redis：session:{session_id} → 热会话（TTL = 2小时）
•	PostgreSQL：会话结束后归档
5. 跨会话长期记忆
对应：用户画像、历史查询模式、领域知识沉淀，分为用户偏好记忆与语义缓存（架构中的 CacheLayer 图2 ）
•	用户偏好记忆
用途：Planner 在规划时参考用户偏好，Router 在路由时优先选择用户偏好的数据源。
JSON
{
  "user_id": "U-1234",
  "preferences": {
    "default_region": "华东区",
    "preferred_data_source": "数仓优先",
    "detail_level": "high",
    "常用指标": ["销售额", "同比增长率", "新签客户数"]
  },
  "query_patterns": [
    {"pattern": "区域销售分析", "frequency": 12, "last_used": "2025-02-10"},
    {"pattern": "客户流失预警", "frequency": 5, "last_used": "2025-02-03"}
  ]
}
•	语义缓存（你架构中的 CacheLayer）
JSON
{
  "cache_key_embedding": [0.12, -0.34, ...],
  "original_query": "Q1华东区销售额同比变化",
  "evidence_cards": ["EC-001", "EC-003", ...],
  "draft_claims": "Q1华东区销售额2.3亿，同比+21.1%...",
  "created_at": "2025-02-10T10:35:00Z",
  "hit_count": 3,
  "ttl": "7d"
}
淘汰策略：
￮	时间衰减：数据类查询 TTL = 7天（数据会更新），知识类查询 TTL = 30天
￮	命中率：hit_count < 2 且超过 3 天 → 淘汰
￮	数据变更：当底层数据源更新时，主动失效相关缓存
存储选择：
￮	PostgreSQL：用户偏好、（结构化，需要精确查询）
￮	向量库（Milvus/Pinecone）：语义缓存（需要相似度检索）
￮	Redis：热用户的偏好缓存（加速读取）

三、其他开源框架记忆管理
参考原文链接 如何管理超长AI对话记忆 - 大模型记忆管理技术方案详解


LLM 应用开发中超长 session记忆管理通常采用以下四个思路解决：
•	窗口滑动（缓冲buffer）
•	信息摘要
•	向量检索
•	知识图谱
以上技术可以视情况混合使用
6. LangChain 记忆管理
7. LlamaIndex 记忆管理
3. LangGraph 记忆管理
4. MeM0 记忆管理


```