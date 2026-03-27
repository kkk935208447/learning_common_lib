"""
Pydantic BaseModel 作为状态：运行时验证与嵌套模型。

目标:
    理解 Pydantic 状态相比 TypedDict 的优势与取舍

关键概念:
    见本文件目标、代码注释与状态/路由设计

关键 API:
    StateGraph + Pydantic BaseModel

目录导航:
    - 从项目根目录: cd src/learning_common_lib/python基础/langgraph教程
    - 当前文件: examples/02_state_deep_dive/04_pydantic_state.py

运行方式:
    - 从项目根目录:
        cd src/learning_common_lib/python基础/langgraph教程
        uv run python examples/02_state_deep_dive/04_pydantic_state.py

预期现象:
    演示运行时类型验证、默认值、嵌套模型，以及验证失败的错误提示

生产提醒:
    Pydantic 验证有性能开销，高吞吐场景可考虑 TypedDict + 手动校验
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from langgraph.graph import END, START, StateGraph


# ---------- 嵌套模型 ----------
class UserProfile(BaseModel):
    """用户资料（嵌套模型）。"""
    name: str
    level: int = Field(default=1, ge=1, le=100)  # 1-100 范围约束


# ---------- 状态定义 ----------
class PydanticState(BaseModel):
    """使用 Pydantic 定义的状态。

    与 TypedDict 的取舍：
    - Pydantic：运行时验证、默认值、嵌套模型、序列化 → 适合复杂业务逻辑
    - TypedDict：零开销、简单直接 → 适合高性能/简单场景
    """
    user: UserProfile
    messages: Annotated[list[str], operator.add] = Field(default_factory=list)
    score: int = 0
    processed: bool = False

    @field_validator("score")
    @classmethod
    def score_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("score 不能为负数")
        return v


# ---------- 节点函数 ----------
def greet_node(state: PydanticState) -> dict:
    """问候节点：根据用户资料生成问候语。"""
    greeting = f"你好, {state.user.name}! 你的等级是 {state.user.level}"
    print(f"[greet] {greeting}")
    return {"messages": [greeting], "score": state.score + 10}


def process_node(state: PydanticState) -> dict:
    """处理节点：标记已处理。"""
    print(f"[process] 当前分数: {state.score}")
    return {"processed": True, "messages": ["处理完成"]}


# ---------- 构建图 ----------
def build_graph() -> StateGraph:
    graph = StateGraph(PydanticState)
    graph.add_node("greet", greet_node)
    graph.add_node("process", process_node)
    graph.add_edge(START, "greet")
    graph.add_edge("greet", "process")
    graph.add_edge("process", END)
    return graph


async def main() -> None:
    app = build_graph().compile()

    # 演示 1：正常执行
    print("=== 正常执行 ===")
    result = await app.ainvoke({
        "user": {"name": "张三", "level": 5},
        "score": 0,
    })
    print(f"结果: messages={result['messages']}, score={result['score']}, "
          f"processed={result['processed']}")

    # 演示 2：默认值生效
    print("\n=== 默认值 ===")
    result = await app.ainvoke(
        PydanticState(
            user=UserProfile(name="李四"),  # level 默认为 1
        )
    )
    print(f"user.level 默认值: {result['user'].level}")

    # 演示 3：验证失败
    print("\n=== 验证失败演示 ===")
    try:
        await app.ainvoke({
            "user": {"name": "王五", "level": 200},  # 超出范围
        })
    except Exception as e:
        print(f"验证错误（level 超范围）: {type(e).__name__}")

    try:
        await app.ainvoke({
            "user": {"name": "赵六"},
            "score": -10,  # 负数
        })
    except Exception as e:
        print(f"验证错误（score 为负）: {type(e).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
