from enum import Enum

# 枚举类的每个成员都是一个实例，每个实例都有属性 code, default_message, http_status

class ErrorCode(Enum):
    """错误码枚举，code/message/http_status 全部从这里派生。"""
    VALIDATION_ERROR = ("VALIDATION_ERROR", "参数校验失败", 422)
    NOT_FOUND = ("NOT_FOUND", "资源不存在", 404)
    DATABASE_ERROR = ("DATABASE_ERROR", "数据库错误", 500)
    INTERNAL_ERROR = ("INTERNAL_ERROR", "服务器内部错误", 500)

    def __init__(self, code: str, message: str, http_status: int):
        self._code = code
        self._message = message
        self._http_status = http_status

    @property
    def code(self) -> str:
        return self._code

    @property
    def default_message(self) -> str:
        return self._message

    @property
    def http_status(self) -> int:
        return self._http_status
    
if __name__ == "__main__":
    a1 = ErrorCode.VALIDATION_ERROR
    print(a1)
    print(a1.code)
    print(a1.default_message)
    print(a1.http_status)
