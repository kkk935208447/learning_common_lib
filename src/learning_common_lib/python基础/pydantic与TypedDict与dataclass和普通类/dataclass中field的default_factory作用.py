
# 1. field 是 dataclasses 库中的一个类，用于定义模型的字段。
# 2. default_factory 是 field 类的一个参数，用于指定字段的默认值工厂函数。
# 3. 当字段的默认值是一个可变对象（如列表、字典等）时，使用 default_factory 可以确保每个实例都有一个独立的默认值，而不是共享同一个默认值。

from dataclasses import dataclass, field
from pydantic import BaseModel, Field
from typing import List, Optional

# 1. dataclass 使用 default_factory 时，每个实例都有一个独立的默认值，而不是共享同一个默认值。

@dataclass
class A:
    a: int
    b: List[int] = field(default_factory=list)

if __name__ == '__main__':
    # 1. 使用 default_factory 时，每个实例都有一个独立的默认值，而不是共享同一个默认值。
    a1 = A(a=1)
    a1.b.append(1)
    print(a1)  # A(a=1, b=[1])
    a2 = A(a=1)
    print(a2)  # A(a=1, b=[])
    print(" - " * 20)




# 2. 当不使用 default_factory 时，默认值会被共享

class B:
    def __init__(self, a = 1, b: Optional[List[int]] = []):
        self.a = a
        self.b = b
# 为了避免默认值被共享，我们可以在类中使用 None 作为默认值，并在初始化时检查是否为 None，然后赋值为空列表。
class C:
    def __init__(self, a = 1, b: Optional[List[int]] = None):
        self.a = a
        self.b = [] if b is None else b


if __name__ == '__main__':
    # 2. 当不使用 default_factory 时，默认值会被共享
    b1 = B(a=1)
    b1.b.append(1)
    print(b1.b)  # B(a=1, b=[1])
    b2 = B(a=1)
    print(b2.b)  # B(a=1, b=[1]), 注意：b2.b 也被修改为 [1]
    print(" - " * 21)


    c1 = C(a=1)
    c1.b.append(1)
    print(c1.b)  # C(a=1, b=[1])
    c2 = C(a=1)
    print(c2.b)  # C(a=1, b=[]) 由于在初始化时检查是否为 None，然后赋值为空列表，所以 c2.b 是一个空列表。
    print(" - " * 22)



