# 编写库学习资料 Skill 实现计划

> **面向代理执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务执行本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 创建项目内 `skills/write-library-tutorials/`，用于指导 AI 编写独立、渐进、覆盖完整且可验证的库学习资料。

**架构：** 使用 `skill-creator` 初始化标准 skill 目录。`SKILL.md` 负责触发条件和工作流程，`references/` 负责教学结构、示例代码规则和验证清单，`.codex/verification-report.md` 记录最终审查结论。

**技术栈：** Codex Skill、Markdown、YAML、`skill-creator` 初始化与校验脚本、Git。

---

## 文件结构

- 新建：`skills/write-library-tutorials/SKILL.md`，定义 skill 触发条件、流程和强制约束。
- 新建：`skills/write-library-tutorials/agents/openai.yaml`，提供 UI 元数据。
- 新建：`skills/write-library-tutorials/references/tutorial-structure.md`，定义教程目录与教学路线结构。
- 新建：`skills/write-library-tutorials/references/example-code-rules.md`，定义 `.py` 示例独立运行与教学说明规则。
- 新建：`skills/write-library-tutorials/references/verification-checklist.md`，定义交付前验证和审查清单。
- 新建：`.codex/verification-report.md`，记录本次创建 skill 的验证结果和评分。
- 新建：`docs/superpowers/plans/2026-06-14-write-library-tutorials-skill.md`，记录本实现计划。

### 任务 1：初始化 Skill 骨架

**文件：**
- 新建：`skills/write-library-tutorials/SKILL.md`
- 新建：`skills/write-library-tutorials/agents/openai.yaml`
- 新建：`skills/write-library-tutorials/references/`

- [ ] **步骤 1：运行初始化脚本**

运行：

```bash
python3 /home/shayuer/.codex/skills/.system/skill-creator/scripts/init_skill.py write-library-tutorials --path skills --resources references --interface display_name="编写库学习资料" --interface short_description="指导编写独立可验证的库教程" --interface default_prompt="使用 $write-library-tutorials 创建渐进式、可独立运行的库教程。"
```

预期：创建 `skills/write-library-tutorials/`，包含 `SKILL.md`、`agents/openai.yaml`、`references/`。

- [ ] **步骤 2：检查初始化结果**

运行：

```bash
find skills/write-library-tutorials -maxdepth 3 -type f -o -type d | sort
```

预期：输出包含 `SKILL.md`、`agents/openai.yaml`、`references`。

### 任务 2：编写 Skill 主文件

**文件：**
- 修改：`skills/write-library-tutorials/SKILL.md`

- [ ] **步骤 1：将 SKILL.md 替换为最终内容**

写入内容应满足：

- frontmatter 仅包含 `name` 和 `description`。
- description 覆盖“编写、补充、重构库学习资料”的触发场景。
- 正文要求读取 3 个 reference 文件。
- 正文要求先分析 3 个项目内模式。
- 正文要求 context7 和 GitHub 代码搜索。
- 正文要求教程模块独立、`.py` 示例尽量独立。

- [ ] **步骤 2：检查 frontmatter**

运行：

```bash
sed -n '1,40p' skills/write-library-tutorials/SKILL.md
```

预期：YAML frontmatter 只含 `name` 和 `description`。

### 任务 3：编写 Reference 文件

**文件：**
- 新建：`skills/write-library-tutorials/references/tutorial-structure.md`
- 新建：`skills/write-library-tutorials/references/example-code-rules.md`
- 新建：`skills/write-library-tutorials/references/verification-checklist.md`

- [ ] **步骤 1：写入教程结构规范**

`tutorial-structure.md` 必须覆盖：

- 推荐目录结构。
- README、roadmap、architecture_map、best_practices、pitfalls、examples、templates、smoke 的职责。
- 从最小示例到生产模板的教学递进。
- 每个模块独立的约束。

- [ ] **步骤 2：写入示例代码规范**

`example-code-rules.md` 必须覆盖：

- `.py` 文件顶部 docstring 字段。
- 独立运行规则。
- 外部服务依赖说明。
- 可观察输出、危险操作边界、测试配套规则。

- [ ] **步骤 3：写入验证清单**

`verification-checklist.md` 必须覆盖：

- 需求字段完整性。
- 教学覆盖面。
- 独立性检查。
- 外部来源记录。
- 本地验证命令。
- 审查评分规则。

### 任务 4：校验和审查

**文件：**
- 新建：`.codex/verification-report.md`

- [ ] **步骤 1：运行 skill 校验**

运行：

```bash
python3 /home/shayuer/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/write-library-tutorials
```

预期：校验通过。

- [ ] **步骤 2：检查引用完整性**

运行：

```bash
rg -n "tutorial-structure|example-code-rules|verification-checklist" skills/write-library-tutorials/SKILL.md
```

预期：三个 reference 文件都被明确引用。

- [ ] **步骤 3：检查占位符**

运行：

```bash
rg -n "TBD|TODO|FIXME|待定|占位|placeholder" skills/write-library-tutorials .codex/verification-report.md docs/superpowers/plans/2026-06-14-write-library-tutorials-skill.md
```

预期：无真实占位符命中。

- [ ] **步骤 4：写入验证报告**

`.codex/verification-report.md` 必须包含：

- 需求字段完整性。
- 交付物映射。
- 依赖与风险评估。
- 本地验证命令和结果。
- 技术评分、战略评分、综合评分。
- 明确建议：通过、退回或需讨论。
- 时间戳：2026-06-14 Asia/Shanghai。

### 任务 5：提交改动

**文件：**
- 暂存：`docs/superpowers/plans/2026-06-14-write-library-tutorials-skill.md`
- 暂存：`skills/write-library-tutorials/`
- 暂存：`.codex/verification-report.md`

- [ ] **步骤 1：查看工作区**

运行：

```bash
git status --short
```

预期：新增计划、skill、验证报告；既有 `.gitignore` 修改和未跟踪 `AGENTS.md` 不纳入本次提交。

- [ ] **步骤 2：提交本次改动**

运行：

```bash
git add docs/superpowers/plans/2026-06-14-write-library-tutorials-skill.md skills/write-library-tutorials .codex/verification-report.md
git commit -m "feat: 新增库学习资料编写 skill"
```

预期：生成一个只包含本任务文件的提交。
