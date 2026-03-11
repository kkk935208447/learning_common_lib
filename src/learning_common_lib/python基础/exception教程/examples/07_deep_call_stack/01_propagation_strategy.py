"""
目标: 模拟 5 层架构，演示三种错误传播策略的效果
关键 API: raise from, traceback
Python 版本: 3.11+
运行命令: uv run python examples/07_deep_call_stack/01_propagation_strategy.py  (从 exception教程/ 目录)
预期现象: 三种策略的 traceback 输出对比——全部透传太长、每层 catch+stringify 信息丢失、边界层转换最清晰
生产提醒: 边界层转换是异常处理架构的核心——在仓储层和外部服务适配层做转换，其他层透传
"""

import traceback
from dataclasses import dataclass, field


# ============================================================
# 基础设施层：模拟数据库
# ============================================================

def database_query(sql: str) -> dict:
    """模拟数据库查询，抛出底层异常。"""
    raise ConnectionRefusedError(
        f"Cannot connect to PostgreSQL: connection refused (port 5432)"
    )


# ============================================================
# 策略一：全部透传（不做任何处理）
# ============================================================
# 每一层只是简单调用下一层，没有 try/except

def repository_get_v1(user_id: int) -> dict:
    """仓储层 v1：直接调用数据库，不处理异常。"""
    return database_query(f"SELECT * FROM users WHERE id = {user_id}")


def service_find_v1(user_id: int) -> dict:
    """服务层 v1：直接调用仓储层。"""
    return repository_get_v1(user_id)


def controller_get_v1(user_id: int) -> dict:
    """控制器层 v1：直接调用服务层。"""
    return service_find_v1(user_id)


def main_v1(user_id: int) -> dict:
    """入口层 v1：直接调用控制器层。"""
    return controller_get_v1(user_id)


# ============================================================
# 策略二：每层 catch + stringify（反模式）
# ============================================================
# 每一层都捕获异常并用字符串包装，导致原始 traceback 丢失

def repository_get_v2(user_id: int) -> dict:
    """仓储层 v2：捕获异常并转为字符串——丢失原始 traceback！"""
    try:
        return database_query(f"SELECT * FROM users WHERE id = {user_id}")
    except Exception as e:
        raise RuntimeError(f"repository error: {e}")  # 丢失原始 traceback!


def service_find_v2(user_id: int) -> dict:
    """服务层 v2：再次捕获并转为字符串——信息进一步丢失！"""
    try:
        return repository_get_v2(user_id)
    except Exception as e:
        raise RuntimeError(f"service error: {e}")  # 再次丢失!


def controller_get_v2(user_id: int) -> dict:
    """控制器层 v2：继续包装字符串。"""
    try:
        return service_find_v2(user_id)
    except Exception as e:
        raise RuntimeError(f"controller error: {e}")


def main_v2(user_id: int) -> dict:
    """入口层 v2：最终只能看到嵌套的字符串错误。"""
    return controller_get_v2(user_id)


# ============================================================
# 策略三：边界层转换 + raise from（正确做法）
# ============================================================

@dataclass
class DatabaseError(Exception):
    """数据库层异常。"""
    code: str = "DB_ERROR"
    message: str = "数据库错误"
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class ServiceError(Exception):
    """服务层异常。"""
    code: str = "SERVICE_ERROR"
    message: str = "服务错误"
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def repository_get_v3(user_id: int) -> dict:
    """仓储层 v3：边界转换——捕获底层异常，raise from 保留异常链。"""
    try:
        return database_query(f"SELECT * FROM users WHERE id = {user_id}")
    except ConnectionRefusedError as e:
        raise DatabaseError(
            code="DB_CONN_REFUSED",
            message="数据库连接失败",
            detail={"user_id": user_id},
        ) from e  # 保留原始异常链!


def service_find_v3(user_id: int) -> dict:
    """服务层 v3：透传 DatabaseError，不需要再包装。"""
    # Service 层：透传 DatabaseError，不需要再包装
    data = repository_get_v3(user_id)
    if data is None:
        raise ServiceError(code="USER_NOT_FOUND", message="用户不存在")
    return data


def controller_get_v3(user_id: int) -> dict:
    """控制器层 v3：不做异常处理，让异常冒泡。"""
    return service_find_v3(user_id)


def main_v3(user_id: int) -> dict:
    """入口层 v3：全局处理器统一处理。"""
    return controller_get_v3(user_id)


# ============================================================
# 策略四（可选增强）：add_note() 在传播过程中补充定位信息
# ============================================================
# Python 3.11+ 的 add_note() 可以在不破坏原始异常链的前提下，
# 在异常传播路径上逐层补充 user_id、order_id 等定位信息。

def repository_get_v4(user_id: int) -> dict:
    """仓储层 v4：边界转换 + add_note() 补充上下文。"""
    try:
        return database_query(f"SELECT * FROM users WHERE id = {user_id}")
    except ConnectionRefusedError as e:
        err = DatabaseError(
            code="DB_CONN_REFUSED",
            message="数据库连接失败",
            detail={"user_id": user_id},
        )
        err.add_note(f"查询用户 user_id={user_id} 时发生")
        raise err from e


def service_find_v4(user_id: int, order_id: str = "ORD-001") -> dict:
    """服务层 v4：透传异常，用 add_note() 补充业务上下文。"""
    try:
        data = repository_get_v4(user_id)
        if data is None:
            raise ServiceError(code="USER_NOT_FOUND", message="用户不存在")
        return data
    except DatabaseError:
        # 不包装、不吞掉，只补充业务上下文后继续传播
        import sys
        exc = sys.exc_info()[1]
        if exc is not None:
            exc.add_note(f"处理订单 order_id={order_id} 时触发")
        raise


def controller_get_v4(user_id: int) -> dict:
    """控制器层 v4：不做异常处理，让异常冒泡。"""
    return service_find_v4(user_id)


def main_v4(user_id: int) -> dict:
    """入口层 v4：全局处理器统一处理。"""
    return controller_get_v4(user_id)


# ============================================================
# 演示运行
# ============================================================

def run_strategy(name: str, func, user_id: int = 1) -> None:
    """运行一个策略并打印 traceback。"""
    print(f"\n{'=' * 60}")
    print(f"策略: {name}")
    print("=" * 60)
    try:
        func(user_id)
    except Exception:
        # 打印完整 traceback
        tb_text = traceback.format_exc()
        print(tb_text)


if __name__ == "__main__":
    # --- 策略一：全部透传 ---
    run_strategy(
        "策略一：全部透传（5 层调用栈全部暴露，泄露底层实现细节）",
        main_v1,
    )

    # --- 策略二：每层 catch + stringify ---
    run_strategy(
        "策略二：每层 catch + stringify（原始异常和 traceback 全部丢失）",
        main_v2,
    )

    # --- 策略三：边界层转换 + raise from ---
    run_strategy(
        "策略三：边界层转换 + raise from（异常链清晰，信息完整）",
        main_v3,
    )

    # --- 策略四：add_note() 补充定位信息 ---
    run_strategy(
        "策略四：边界层转换 + add_note()（异常链完整，且逐层补充了 user_id/order_id）",
        main_v4,
    )

    # --- 总结 ---
    print("\n" + "=" * 60)
    print("=== 传播策略总结 ===")
    print("=" * 60)
    print("""
规则 1: 基础设施层（数据库、外部 API）→ 抛出原始异常
规则 2: 仓储层 → 捕获底层异常，raise XxxError from e（边界转换）
规则 3: 服务层 → 业务逻辑判断，必要时 raise；底层异常透传
规则 4: 控制器层 → 不做异常处理，让异常冒泡到全局处理器
规则 5: 全局处理器 → AppError 转统一 JSON，未知异常转 500 + 记录日志

关键洞察:
  - 策略一（全部透传）：traceback 包含所有 5 层帧，底层错误信息直接暴露给调用者
  - 策略二（每层 stringify）：原始异常类型和 traceback 全部丢失，只剩嵌套字符串
  - 策略三（边界转换）：只在仓储层做一次转换，异常链完整保留，错误信息清晰分层
  - 策略四（add_note 增强）：在策略三基础上，用 add_note() 逐层补充定位信息
    （user_id、order_id 等），不破坏异常链，traceback 末尾可看到所有 note
""")
