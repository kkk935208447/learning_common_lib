# LangGraph 学习路线图

## 基础篇（01-06）— 建议 2-3 天

| 章节 | 主题 | 前置依赖 |
|------|------|----------|
| 01 | 图基础 (Graph Fundamentals) | 无 |
| 02 | 状态深入 (State Deep Dive) | 01 |
| 03 | 边与路由 (Edges & Routing) | 01, 02 |
| 04 | 工具调用 (Tool Calling) | 01, 02, 03 |
| 05 | 检查点 (Checkpointing) | 01, 02 |
| 06 | 流式输出 (Streaming) | 01, 02 |

掌握目标：能独立构建带状态管理、条件路由、工具调用的单 Agent 图。

## 进阶篇（07-13）— 建议 3-5 天

| 章节 | 主题 | 前置依赖 |
|------|------|----------|
| 07 | 子图组合 (Subgraph Composition) | 01-03 |
| 08 | 人机协作 (Human-in-the-Loop) | 05 |
| 09 | 错误与韧性 (Error & Resilience) | 01-03 |
| 10 | 多 Agent (Multi-Agent) | 03, 07 |
| 11 | 动态与并行 (Dynamic & Parallel) | 03, 07 |
| 12 | 记忆与存储 (Memory & Store) | 05 |
| 13 | 函数式 API (Functional API) | 01-03 |

掌握目标：能设计多 Agent 协作系统，处理复杂错误场景，使用高级特性。

## 工程实战篇（14-16）— 建议 2-3 天

| 章节 | 主题 | 前置依赖 |
|------|------|----------|
| 14 | 测试与调试 (Testing & Debugging) | 01-06 |
| 15 | 生产部署 (Production Deployment) | 05, 06, 09 |
| 16 | AgenticRAG 模式 (AgenticRAG Patterns) | 全部 |

掌握目标：能将 LangGraph 应用部署到生产环境，具备测试、监控、运维能力。

## 依赖关系图

```
01 ──→ 02 ──→ 03 ──→ 04
 │      │      │
 │      ├──→ 05 ──→ 06
 │      │      │
 │      │      ├──→ 08 (Human-in-the-Loop)
 │      │      └──→ 12 (Memory & Store)
 │      │
 └──→ 03 ──→ 07 ──→ 10 (Multi-Agent)
              │      └──→ 11 (Dynamic & Parallel)
              │
        09 (Error & Resilience, 需 01-03)
        13 (Functional API, 需 01-03)
        14 (Testing, 需 01-06)
        15 (Production, 需 05+06+09)
        16 (AgenticRAG, 需全部)
```

## 建议学习方式

1. 每章先读示例代码的注释，理解设计意图
2. 运行示例，观察输出
3. 修改参数，验证理解
4. 参考 `templates/` 中的生产级实现
5. 用 `smoke/run_all_examples.py` 验证环境
