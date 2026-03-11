"""
目标: 设计一棵项目级异常树，演示在不同层级捕获的效果
关键 API: Exception 继承
Python 版本: 3.11+
运行命令: uv run python examples/02_custom_exceptions/02_exception_hierarchy.py  (从 exception教程/ 目录)
预期现象: 展示异常树结构和不同层级捕获的行为
生产提醒: 异常树设计和数据模型设计一样重要，提前规划好层级关系
"""


# ── 异常树定义 ──
#
# AppError
# ├── ClientError (4xx)
# │   ├── NotFoundError
# │   ├── AppValidationError  (避免与 Pydantic 的 ValidationError 撞名)
# │   └── AuthenticationError
# └── ServerError (5xx)
#     ├── DatabaseError
#     └── ExternalServiceError


class AppError(Exception):
    """应用顶层异常基类。"""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.code}] ({self.status_code}) {self.message}"


# ── 客户端错误 (4xx) ──

class ClientError(AppError):
    """客户端错误基类。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(code, message, status_code)


class NotFoundError(ClientError):
    """资源未找到 (404)。"""

    def __init__(self, message: str = "资源未找到") -> None:
        super().__init__("NOT_FOUND", message, 404)


class AppValidationError(ClientError):
    """请求参数校验失败 (422)。避免与 Pydantic 的 ValidationError 撞名。"""

    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__("VALIDATION_ERROR", message, 422)


class AuthenticationError(ClientError):
    """认证失败 (401)。"""

    def __init__(self, message: str = "认证失败") -> None:
        super().__init__("AUTH_ERROR", message, 401)


# ── 服务端错误 (5xx) ──

class ServerError(AppError):
    """服务端错误基类。"""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        super().__init__(code, message, status_code)


class DatabaseError(ServerError):
    """数据库错误 (500)。"""

    def __init__(self, message: str = "数据库错误") -> None:
        super().__init__("DB_ERROR", message, 500)


class ExternalServiceError(ServerError):
    """外部服务调用失败 (502)。"""

    def __init__(self, message: str = "外部服务不可用") -> None:
        super().__init__("EXTERNAL_SERVICE_ERROR", message, 502)


# ── 演示不同层级的捕获效果 ──

def demo_catch_specific() -> None:
    """演示 1：捕获具体异常。"""
    print("=" * 55)
    print("演示 1：捕获具体异常 — except NotFoundError")
    print("=" * 55)
    for exc in [NotFoundError("用户不存在"), AppValidationError("邮箱格式错误")]:
        try:
            raise exc
        except NotFoundError as e:
            print(f"  [NotFoundError] 捕获: {e}")
        except AppError as e:
            print(f"  [AppError 兜底]  未被 NotFoundError 匹配: {e}")


def demo_catch_middle() -> None:
    """演示 2：捕获中间层 ClientError。"""
    print(f"\n{'='*55}")
    print("演示 2：捕获中间层 — except ClientError")
    print("=" * 55)
    test_cases = [
        NotFoundError("用户不存在"),
        AppValidationError("邮箱格式错误"),
        AuthenticationError("token 过期"),
        DatabaseError("连接池耗尽"),
    ]
    for exc in test_cases:
        try:
            raise exc
        except ClientError as e:
            print(f"  [ClientError]  捕获 {type(e).__name__}: {e}")
        except AppError as e:
            print(f"  [AppError 兜底] 非客户端错误 {type(e).__name__}: {e}")


def demo_catch_top() -> None:
    """演示 3：捕获顶层 AppError。"""
    print(f"\n{'='*55}")
    print("演示 3：捕获顶层 — except AppError")
    print("=" * 55)
    test_cases = [
        NotFoundError("用户不存在"),
        DatabaseError("连接池耗尽"),
        ExternalServiceError("支付网关超时"),
    ]
    for exc in test_cases:
        try:
            raise exc
        except AppError as e:
            print(f"  [AppError] 捕获 {type(e).__name__}: {e}")


def demo_non_app_error() -> None:
    """演示 4：非 AppError 异常不会被 AppError 捕获。"""
    print(f"\n{'='*55}")
    print("演示 4：非 AppError 异常不会被 AppError handler 捕获")
    print("=" * 55)
    try:
        raise RuntimeError("意料之外的运行时错误")
    except AppError as e:
        print(f"  [AppError] 捕获: {e}")
    except Exception as e:
        print(f"  [Exception] RuntimeError 逃逸了 AppError handler: {e}")
        print(f"  → {type(e).__name__} 不是 AppError 的子类")


if __name__ == "__main__":
    demo_catch_specific()
    demo_catch_middle()
    demo_catch_top()
    demo_non_app_error()
