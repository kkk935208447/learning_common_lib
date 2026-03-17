"""Typed runtime settings for database, Redis, upload limits, and schedules."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


# 统一把环境变量解析、默认值和派生连接串收口在一个 Settings 对象里。
class Settings(BaseSettings):
    # demo 统一用 `MIN_RAG_` 前缀，方便和仓库里其他案例共存。
    model_config = SettingsConfigDict(
        env_prefix="MIN_RAG_",
        case_sensitive=False,
        extra="ignore",
    )

    # 默认连接都指向本机，方便本地演示直接跑起来。
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "agentic_rag_min_demo"

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = "123456"
    redis_broker_db: int = 0
    redis_backend_db: int = 1
    redis_lock_db: int = 2

    runtime_dir: Path = BASE_DIR / ".runtime"

    celery_eager: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8091
    auto_create_tables_on_startup: bool = False

    default_kb_code: str = "default"

    # 这些参数共同决定“同一个版本号”会被切成什么 chunks。
    parser_chunk_size: int = 500
    parser_chunk_overlap: int = 50
    parser_version: str = "min-demo-parser-v1"
    embedding_model: str = "deterministic-mock-v1"
    embedding_dim: int = 8
    upload_max_bytes: int = 20 * 1024 * 1024
    upload_allowed_mime_types: tuple[str, ...] = (
        "text/plain",
        "text/markdown",
        "application/pdf",
    )

    task_max_retries: int = 5
    task_retry_base_seconds: int = 60
    outbox_dispatch_scan_seconds: int = 5
    outbox_cleanup_days: int = 7
    janitor_scan_limit: int = 100
    janitor_schedule_seconds: int = 30
    lock_ttl_seconds: int = 300

    @computed_field
    @property
    def mysql_dsn(self) -> str:
        # 业务库连接给 API、Worker 和脚本使用。
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @computed_field
    @property
    def mysql_admin_dsn(self) -> str:
        # 管理连接只用于建库这类管理动作。
        return (
            f"mysql+asyncmy://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/mysql"
        )

    @computed_field
    @property
    def redis_broker_url(self) -> str:
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
            f"/{self.redis_broker_db}"
        )

    @computed_field
    @property
    def redis_backend_url(self) -> str:
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
            f"/{self.redis_backend_db}"
        )

    @computed_field
    @property
    def redis_lock_url(self) -> str:
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
            f"/{self.redis_lock_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 全局只构造一份配置，避免重复读取环境变量和重复创建 runtime 目录。
    settings = Settings()
    # 初始化时顺手保证运行时目录存在，避免每个适配器都重复 mkdir。
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    return settings
