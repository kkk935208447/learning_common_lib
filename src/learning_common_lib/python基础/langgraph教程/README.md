# LangGraph 教程（基础 + 高阶 + 企业模板）

## 定位

面向已有 Python 基础的开发者，从零掌握 LangGraph 状态图编程，覆盖图构建、状态管理、路由、工具调用、持久化、流式、子图、人机协作、错误处理、多 Agent、动态并行、记忆存储、函数式 API、测试调试、生产部署、AgenticRAG 模式共 16 章渐进式示例，外加一套企业级可复用模板。

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | ≥3.11 | 运行环境 |
| langgraph | ≥0.2 | 核心框架 |
| langchain-core | ≥0.3 | 消息与工具抽象 |
| langchain-community | ≥0.3 | FakeListChatModel 等 |
| redis | ≥5.0 | Checkpoint 持久化 |
| celery[redis] | ≥5.3 | 任务队列桥接 |
| fastapi | ≥0.110 | Web 服务集成 |
| uvicorn | ≥0.29 | ASGI 服务器 |

## 环境准备

```bash
# pip
pip install langgraph langchain-core langchain-community redis "celery[redis]" fastapi uvicorn

# uv
uv add langgraph langchain-core langchain-community redis "celery[redis]" fastapi uvicorn
```

## 目录结构

```
langgraph教程/
├── README.md                  # 本文件
├── roadmap.md                 # 学习路线图
├── architecture_map.md        # 架构全景图
├── best_practices.md          # 最佳实践
├── pitfalls.md                # 常见陷阱
├── examples/                  # 16 章示例代码
│   ├── 01_graph_fundamentals/
│   ├── 02_state_deep_dive/
│   ├── ...
│   └── 16_agentic_rag_patterns/
├── templates/                 # 企业级可复用模板
│   ├── README.md
│   ├── state_schemas.py
│   ├── safe_node.py
│   ├── graph_builder.py
│   ├── checkpoint_manager.py
│   ├── multi_agent_orchestrator.py
│   ├── celery_graph_bridge.py
│   └── fastapi_graph_app.py
└── smoke/
    └── run_all_examples.py    # 批量运行测试
```

## 快速开始

```bash
# 运行第一个示例
python examples/01_graph_fundamentals/01_minimal_graph.py

# 批量运行所有示例
python smoke/run_all_examples.py
```

## Redis 连接约定

| DB | 用途 | URL |
|----|------|-----|
| 0 | Checkpoint 持久化 | `redis://:123456@localhost:6379/0` |
| 1 | Store 存储 | `redis://:123456@localhost:6379/1` |
| 2 | 缓存 | `redis://:123456@localhost:6379/2` |

## 学习路线概览

| 阶段 | 章节 | 主题 | 建议时间 |
|------|------|------|----------|
| 基础篇 | 01 | 图基础 | 半天 |
| 基础篇 | 02 | 状态深入 | 半天 |
| 基础篇 | 03 | 边与路由 | 半天 |
| 基础篇 | 04 | 工具调用 | 半天 |
| 基础篇 | 05 | 检查点 | 半天 |
| 基础篇 | 06 | 流式输出 | 半天 |
| 进阶篇 | 07 | 子图组合 | 半天 |
| 进阶篇 | 08 | 人机协作 | 半天 |
| 进阶篇 | 09 | 错误与韧性 | 1 天 |
| 进阶篇 | 10 | 多 Agent | 1 天 |
| 进阶篇 | 11 | 动态与并行 | 半天 |
| 进阶篇 | 12 | 记忆与存储 | 半天 |
| 进阶篇 | 13 | 函数式 API | 半天 |
| 工程篇 | 14 | 测试与调试 | 1 天 |
| 工程篇 | 15 | 生产部署 | 1 天 |
| 工程篇 | 16 | AgenticRAG 模式 | 1 天 |

详细路线图见 [roadmap.md](roadmap.md)。
