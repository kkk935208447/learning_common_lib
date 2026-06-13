# 编写库学习资料 Skill 设计

## 目标

在项目目录下创建 `skills/write-library-tutorials/`，作为后续指导 AI 编写各类库学习资料的项目内 skill。该 skill 必须体现教师视角，帮助 AI 为 FastAPI、SQLAlchemy、asyncio、Celery、TaskIQ、LangGraph 等库或主题编写从易到难、覆盖面完整、可独立运行、可验证的学习资料。

## 范围

本次只创建一个通用教学资料编写 skill，不为某个具体库生成新教程内容，也不修改既有教程模块。

覆盖内容：

- 教程目录结构规范。
- 示例 `.py` 文件独立性规范。
- 从官方文档、context7、GitHub 开源实现到项目资料的转化流程。
- 教师视角的学习路线设计方法。
- 可重复验证和审查报告要求。

不覆盖内容：

- 自动生成某个库的完整教程。
- 自动扫描并重写既有教程。
- 为所有库生成统一脚手架脚本。
- 修改项目依赖或运行环境。

## 现有模式分析

已抽样分析至少 3 类现有实现：

1. `src/learning_common_lib/redis_lession/celery教程与Redlock/`
   - 具备 `README.md`、`roadmap.md`、`architecture_map.md`、`best_practices.md`、`pitfalls.md`、`examples/`、`templates/`、`smoke/`。
   - 教程以阶段化路线组织，强调两终端运行、Redis 清理、任务队列可靠性边界、生产级模板。

2. `src/learning_common_lib/mysql_lession/`
   - 具备完整目录结构说明、学习路线概览、核心原则、运行命令和学完后的能力目标。
   - 文档强调 SQLAlchemy 2.0 风格、异步 Session 生命周期、Repository 模式、性能与错误边界。

3. `src/learning_common_lib/python基础/asyncio教程/`
   - `roadmap.md` 从基础协程、结构化并发、超时、取消、背压、重试、阻塞桥接到服务生命周期递进。
   - 示例 `.py` 顶部使用模块级 docstring 描述目标、关键 API、Python 版本、运行命令、预期现象、生产提醒。

4. `src/learning_common_lib/python基础/fastapi教程/`
   - 学习路线以阶段划分，每阶段包含“学什么”“为什么在这里”“关键收获”。
   - 示例文件常配套测试文件，适合体现“每个示例独立验证”的项目风格。

## 依赖与集成点

输入：

- 用户指定的库、框架、SDK 或主题。
- 当前项目已有教程目录和文档风格。
- 官方文档、context7 查询结果、GitHub 开源实现示例。

输出：

- `skills/write-library-tutorials/SKILL.md`
- `skills/write-library-tutorials/agents/openai.yaml`
- `skills/write-library-tutorials/references/tutorial-structure.md`
- `skills/write-library-tutorials/references/example-code-rules.md`
- `skills/write-library-tutorials/references/verification-checklist.md`
- `.codex/verification-report.md`

环境需求：

- 使用项目当前文件系统，不新增运行依赖。
- 使用 `skill-creator` 的 `scripts/init_skill.py` 初始化 skill。
- 使用 `skill-creator` 的 `scripts/quick_validate.py` 校验 skill。

## 推荐方案

采用轻量 `SKILL.md` 加少量 reference 契约文件的结构。

目录结构：

```text
skills/write-library-tutorials/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    ├── tutorial-structure.md
    ├── example-code-rules.md
    └── verification-checklist.md
```

选择理由：

- `SKILL.md` 保持短小，主要描述触发条件、流程和强制约束。
- 教学结构、示例代码规范、验证清单拆分为 reference，避免主文件过长。
- 当前需求是指导 AI 写学习资料，不需要引入脚手架脚本，避免过早自动化。

## Skill 行为设计

`SKILL.md` 应要求 AI 在编写或修改教程前执行以下流程：

1. 扫描项目内至少 3 个既有教程或示例模式，提炼目录结构、命名习惯、文档风格、测试方式。
2. 对编程库、框架、SDK、API 优先使用 context7 查询官方或近似官方文档。
3. 使用 `github.search_code` 查询成熟开源实现，学习真实项目中的最佳实践，但不照搬代码。
4. 先设计教学路线，再写文档和示例。
5. 每个教程模块必须相互独立，不能要求读者先学完另一个模块才能运行当前模块。
6. 每个示例 `.py` 文件尽量独立运行、独立解释、独立验证。
7. 示例顶部写明目标、关键 API、版本要求、运行命令、预期现象、生产提醒。
8. 完成后运行可重复验证命令，并生成 `.codex/verification-report.md`。

## 教师视角要求

每个教程需要按从易到难组织：

1. 最小可运行示例。
2. 核心概念与基本参数。
3. 参数矩阵、配置边界和常见组合。
4. 错误处理、异常恢复、重试、超时、幂等或资源清理。
5. 性能、安全、并发、生命周期等生产关注点。
6. 高阶用法、组合模式、企业级模板。
7. smoke 测试或自动化测试。

每个知识点至少回答：

- 学什么。
- 为什么现在学。
- 怎么运行。
- 应观察什么现象。
- 生产中如何使用。
- 容易踩什么坑。

## 示例独立性规则

示例 `.py` 文件默认满足：

- 可以从所属教程目录使用 `uv run python examples/.../xx.py` 单独运行。
- 不依赖前一个示例已经创建的数据库表、Redis key、临时文件、后台 worker 状态或全局缓存。
- 如果依赖外部服务，必须在文件顶部和 README 中写清准备步骤。
- 如果必须复用共享模板，只允许依赖 `templates/` 或明确说明的基础设施模块。
- 示例应包含可观察输出，避免运行后无反馈。
- 示例不隐藏危险操作，清理数据库、Redis、文件系统前必须限定教程专用资源。

## 验证方案

实施完成后运行：

```bash
/home/shayuer/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/write-library-tutorials
```

并做以下检查：

- `SKILL.md` frontmatter 仅包含 `name` 和 `description`。
- skill 名称与目录名一致。
- `agents/openai.yaml` 与 skill 内容一致。
- `SKILL.md` 明确引用 3 个 reference 文件及读取时机。
- reference 文件无占位符、无英文说明性文本。
- `.codex/verification-report.md` 包含技术评分、战略评分、综合评分、审查结论和时间戳。

## 风险与处理

风险 1：skill 过度详细导致上下文占用过高。  
处理：保持 `SKILL.md` 精简，将细则放入 references。

风险 2：规则过硬导致不同库教程难以适配。  
处理：把独立性、验证、教师视角设为强约束；把目录文件数量作为推荐结构，允许按库复杂度裁剪并说明原因。

风险 3：外部文档检索失败。  
处理：在验证报告中记录失败原因，使用项目已有模式和可访问的官方资料替代，不凭记忆写不确定 API。

风险 4：示例确实需要共享环境。  
处理：允许依赖外部服务或模板，但必须显式写明准备步骤、清理方式和独立验证命令。

## 验收标准

- 项目内存在可用的 `skills/write-library-tutorials/`。
- skill 能清晰触发“编写、补充、重构库学习资料”的任务。
- skill 明确要求简体中文、教师视角、由浅入深、广覆盖、高阶用法、独立教程和独立示例。
- skill 明确要求 context7 和 GitHub 代码搜索的使用与记录。
- skill 通过 `quick_validate.py`。
- `.codex/verification-report.md` 给出通过/退回/需讨论结论。
