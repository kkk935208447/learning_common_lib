# Milvus 教程模板

这些模板从教程示例中提炼出来，目标是给真实项目迁移时一个清晰的起点，而不是替代项目自己的配置、日志、监控和错误体系。

## 模板清单

| 模板 | 解决什么 | 不解决什么 |
|------|----------|------------|
| `settings.py` | 统一读取 Milvus URI、token、集合名前缀和向量维度 | 不接管项目级配置中心 |
| `vector_utils.py` | 校验维度、归一化向量、构造教学数据 | 不生成真实 embedding |
| `index_catalog.py` | 汇总常见索引类型、构建参数、搜索参数和选型说明 | 不替代真实数据集压测 |
| `sync_repository.py` | 用同步 `MilvusClient` 管理 collection、写入、搜索、查询、删除 | 不适合 Web 服务高并发请求路径 |
| `async_repository.py` | 用 `AsyncMilvusClient` 管理异步检索、批量并发和连接生命周期 | 不封装完整 RAG、权限、租户和可观测性 |

## 使用方式

从仓库根目录运行，推荐使用绝对包路径导入具体子模块，IDE 可以直接点击进入源码：

```python
from learning_common_lib.python基础.milvus教程.templates import Document
from learning_common_lib.python基础.milvus教程.templates.index_catalog import get_index_profile
from learning_common_lib.python基础.milvus教程.templates.sync_repository import SyncMilvusRepository
from learning_common_lib.python基础.milvus教程.templates.vector_utils import build_demo_chunks
```

验证模板包导入：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -c "from learning_common_lib.python基础.milvus教程.templates.sync_repository import SyncMilvusRepository; print(SyncMilvusRepository.__name__)"
```

运行纯 Python 模板：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.vector_utils
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.index_catalog
```

运行真实 Milvus 模板：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.sync_repository
UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.async_repository
UV_CACHE_DIR=/tmp/uv-cache uv run python src/learning_common_lib/python基础/milvus教程/templates/sync_repository.py
UV_CACHE_DIR=/tmp/uv-cache uv run python src/learning_common_lib/python基础/milvus教程/templates/async_repository.py
```

如果你使用 Docker Standalone，本地默认通常不需要 token：

```bash
MILVUS_URI=http://localhost:19530 UV_CACHE_DIR=/tmp/uv-cache uv run python -m learning_common_lib.python基础.milvus教程.templates.sync_repository
```

如果连接云服务或开启认证的服务端，再通过 `MILVUS_TOKEN` 传入认证信息。PyMilvus 也支持 `user/password` 分开传入，本模板为了保持教学配置简洁没有展开。

## 导入约定

`examples/` 示例为了直观学习，不导入本目录模板；每个示例保留必要的局部 helper。`templates/` 才承担真实项目迁移骨架职责。

包外使用绝对导入：

```python
from learning_common_lib.python基础.milvus教程.templates.settings import load_settings
```

模板包内优先使用相对导入；为了支持直接运行单个模板文件，可以在相对导入失败时回退到教程目录下的 `templates.*` 绝对导入：

```python
try:
    from .settings import load_settings
    from .vector_utils import Document
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from templates.settings import load_settings  # type: ignore[no-redef]
    from templates.vector_utils import Document  # type: ignore[no-redef]
```

`examples/` 仍保持自包含，不依赖这类 fallback。模板运行既可以用 `python -m learning_common_lib.python基础.milvus教程.templates.<module>` 验证包内相对导入，也可以直接运行 `templates/<module>.py` 验证回退路径。

## 生产迁移边界

生产项目中建议保留这些边界：

- embedding 生成和向量库写入分层，不要在仓储里直接调用大模型 API。
- 集合名必须带业务前缀或租户前缀，清理逻辑只能删除受控命名空间。
- 写入前校验维度，避免把错误 embedding 写入 Milvus 后才在检索时暴露。
- 同步客户端用于脚本和离线任务；FastAPI、异步 worker 或批量查询使用 `AsyncMilvusClient`。
- `AsyncMilvusClient` 在 PyMilvus 3.0 文档和源码中仍标注为实验性能力，升级前要用 smoke 或集成测试验证关键接口。
