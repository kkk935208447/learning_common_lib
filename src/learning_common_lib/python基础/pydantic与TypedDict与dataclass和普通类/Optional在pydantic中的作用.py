

from typing import Optional, List, Dict, Union, Any, TypedDict
from dataclasses import dataclass
from pydantic import Field, BaseModel

# Optional 是一个类型提示，用于表示一个值可能是 None，也可能是指定的类型。
# Optional[str] 等价于 str | None

class A(BaseModel):
    a: int 
    b: Optional[str] = None   

class B(BaseModel):
    a: int 
    b: str = None

if __name__ == '__main__':
    a = A(a = 1, b = None)
    print(a)  # a=1 b=None
    print("-----------------")

    # 报错：b 字段不能为 None, 没有使用 Optional 类型提示
    b = B(a = 1, b = None)
    print(b)  






