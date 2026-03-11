"""
目标: 用标准库 logging 输出 JSON 结构化日志，包含 request_id、异常信息、traceback
关键 API: logging.Formatter, logging.LogRecord, json
Python 版本: 3.11+
运行命令: uv run python examples/04_traceback_logging/03_json_structured_logging.py  (从 exception教程/ 目录)
预期现象: 日志以 JSON 格式输出，每行一个 JSON 对象，方便对接 ELK/Datadog
生产提醒: 生产环境可用 python-json-logger 等库；本示例用标准库实现，展示原理
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from datetime import datetime, timezone


# ============================================================
# JSONFormatter — 自定义 JSON 日志格式化器
# ============================================================

class JSONFormatter(logging.Formatter):
    """将 LogRecord 格式化为单行 JSON。

    输出字段:
      - timestamp: ISO 8601 格式 (UTC)
      - level: 日志级别
      - logger: logger 名称
      - message: 日志消息
      - request_id: 请求 ID（从 extra 中获取）
      - exception: 异常信息（仅在有异常时出现）
      - traceback: 完整 traceback（仅在有异常时出现）
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 从 extra 中提取 request_id（如果有）
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        # 从 extra 中提取其他自定义字段
        if hasattr(record, "operation"):
            log_data["operation"] = record.operation

        # 异常信息
        if record.exc_info and record.exc_info[1] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else "Unknown",
                "message": str(exc_value),
            }
            log_data["traceback"] = traceback.format_exception(
                exc_type, exc_value, exc_tb
            )

        return json.dumps(log_data, ensure_ascii=False)


# ============================================================
# 模拟业务异常
# ============================================================

class PaymentError(Exception):
    """支付失败异常。"""
    pass


class OrderError(Exception):
    """订单处理异常。"""
    pass


def process_payment(order_id: str) -> None:
    """模拟支付处理失败。"""
    raise PaymentError(f"订单 {order_id} 支付网关超时")



# ============================================================
# 配置 JSON logger
# ============================================================

def create_json_logger(name: str = "app") -> logging.Logger:
    """创建一个输出 JSON 格式的 logger。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不传播到 root logger

    # 避免重复添加 handler
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    return logger


# ============================================================
# 演示
# ============================================================

def demo_basic_json_log() -> None:
    """演示 1：基本 JSON 日志输出。"""
    print("=" * 65)
    print("演示 1：基本 JSON 日志 — 每行一个 JSON 对象")
    print("=" * 65)

    logger = create_json_logger("demo.basic")
    logger.info("服务启动", extra={"request_id": "N/A", "operation": "startup"})
    logger.warning("配置项缺失，使用默认值", extra={"request_id": "N/A", "operation": "config"})
    print()


def demo_exception_json_log() -> None:
    """演示 2：异常时的 JSON 日志（包含 traceback）。"""
    print("=" * 65)
    print("演示 2：异常 JSON 日志 — 包含 exception 和 traceback 字段")
    print("=" * 65)

    logger = create_json_logger("demo.exception")
    request_id = str(uuid.uuid4())[:8]

    try:
        process_payment("ORD-001")
    except PaymentError:
        logger.exception(
            "支付处理失败",
            extra={"request_id": request_id, "operation": "process_payment"},
        )
    print()


def demo_chained_exception_json_log() -> None:
    """演示 3：异常链的 JSON 日志。"""
    print("=" * 65)
    print("演示 3：异常链 JSON 日志 — raise from 的 traceback 完整保留")
    print("=" * 65)

    logger = create_json_logger("demo.chain")
    request_id = str(uuid.uuid4())[:8]

    try:
        try:
            process_payment("ORD-002")
        except PaymentError as e:
            raise OrderError(f"订单处理失败: 支付环节异常") from e
    except OrderError:
        logger.exception(
            "订单处理失败",
            extra={"request_id": request_id, "operation": "process_order"},
        )
    print()


if __name__ == "__main__":
    demo_basic_json_log()
    demo_exception_json_log()
    demo_chained_exception_json_log()

    print("=" * 65)
    print("JSON 结构化日志要点")
    print("=" * 65)
    print("""
  1. 每行一个 JSON 对象 → 日志系统可直接解析，无需正则
  2. request_id 贯穿请求生命周期 → 一键检索整条链路
  3. exception + traceback 字段 → 结构化存储，方便聚合告警
  4. 生产环境建议:
     - 用 python-json-logger 库（功能更完整）
     - 或直接用本示例的 JSONFormatter 作为起点
     - 配合 ELK / Datadog / CloudWatch Logs 使用
""")
