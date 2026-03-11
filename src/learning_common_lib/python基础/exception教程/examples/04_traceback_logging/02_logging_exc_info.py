"""
目标: 演示 logging.exception() 和 exc_info 的用法，以及如何附加结构化上下文
关键 API: logging.exception, logging.error(exc_info=True), LoggerAdapter
Python 版本: 3.11+
运行命令: uv run python examples/04_traceback_logging/02_logging_exc_info.py  (从 exception教程/ 目录)
预期现象: 展示不同日志方法的输出格式，以及带 request_id 的结构化日志
生产提醒: 生产环境建议用结构化日志（JSON 格式），方便日志系统解析和检索
"""

import logging
import uuid


# ── 基础配置 ──

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("demo")


# ── 模拟业务异常 ──

class PaymentError(Exception):
    """支付失败异常。"""
    pass


def process_payment(order_id: str) -> None:
    """模拟支付处理失败。"""
    raise PaymentError(f"订单 {order_id} 支付网关超时")


# ── 方法一：logger.exception() ──

def demo_logger_exception() -> None:
    """logger.exception() 自动附带 traceback，日志级别为 ERROR。"""
    print("=" * 65)
    print("方法一：logger.exception('msg') — 自动附带 traceback")
    print("=" * 65)
    try:
        process_payment("ORD-001")
    except PaymentError:
        logger.exception("支付处理失败")
    print()


# ── 方法二：logger.error(exc_info=True) ──

def demo_exc_info_true() -> None:
    """logger.error(exc_info=True) — 等价于 logger.exception()。"""
    print("=" * 65)
    print("方法二：logger.error('msg', exc_info=True) — 等价写法")
    print("=" * 65)
    try:
        process_payment("ORD-002")
    except PaymentError:
        logger.error("支付处理失败", exc_info=True)
    print()


# ── 方法三：logger.error(exc_info=False) — 对比 ──

def demo_exc_info_false() -> None:
    """logger.error(exc_info=False) — 不带 traceback。"""
    print("=" * 65)
    print("方法三：logger.error('msg', exc_info=False) — 不带 traceback（对比）")
    print("=" * 65)
    try:
        process_payment("ORD-003")
    except PaymentError as e:
        logger.error("支付处理失败: %s", e, exc_info=False)
    print()


# ── 方法四：结构化上下文 — LoggerAdapter ──

class ContextAdapter(logging.LoggerAdapter):
    """给日志消息自动附加上下文字段。"""

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = self.extra
        prefix = " | ".join(f"{k}={v}" for k, v in extra.items())
        return f"[{prefix}] {msg}", kwargs


def demo_structured_context() -> None:
    """用 LoggerAdapter 附加 request_id, operation 等字段。"""
    print("=" * 65)
    print("方法四：结构化上下文 — LoggerAdapter 附加 request_id")
    print("=" * 65)

    request_id = str(uuid.uuid4())[:8]
    context_logger = ContextAdapter(logger, {
        "request_id": request_id,
        "operation": "process_payment",
    })

    context_logger.info("开始处理支付请求")
    try:
        process_payment("ORD-004")
    except PaymentError:
        context_logger.exception("支付处理失败")
    print()


# ── 方法五：自定义 Formatter ──

def demo_custom_formatter() -> None:
    """自定义 Formatter 展示带上下文的日志格式。"""
    print("=" * 65)
    print("方法五：自定义 Formatter — 带上下文字段的日志格式")
    print("=" * 65)

    # 创建独立的 handler 和 formatter
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | "
            "req=%(request_id)s | op=%(operation)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)

    # 创建独立 logger 避免影响其他演示
    custom_logger = logging.getLogger("demo.custom")
    custom_logger.addHandler(handler)
    custom_logger.propagate = False  # 不传播到父 logger

    request_id = str(uuid.uuid4())[:8]
    extra = {"request_id": request_id, "operation": "process_payment"}

    custom_logger.info("开始处理支付请求", extra=extra)
    try:
        process_payment("ORD-005")
    except PaymentError:
        custom_logger.exception("支付处理失败", extra=extra)
    print()


if __name__ == "__main__":
    demo_logger_exception()
    demo_exc_info_true()
    demo_exc_info_false()
    demo_structured_context()
    demo_custom_formatter()
