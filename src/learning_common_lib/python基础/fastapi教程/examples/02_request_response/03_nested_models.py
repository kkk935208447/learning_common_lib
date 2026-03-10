"""
目标: 演示嵌套模型、list 字段和 field_validator 自定义校验
关键 API: APIRouter, BaseModel, Field, field_validator, JSONResponse
Python 版本: 3.11+
运行命令: uv run python examples/02_request_response/03_nested_models.py  (手动探索 /docs)
测试命令: uv run python examples/02_request_response/03_nested_models_test.py
生产提醒: validator 只做格式校验，业务规则校验放在 service 层
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Pydantic 嵌套模型
# ---------------------------------------------------------------------------


class Address(BaseModel):
    city: str
    street: str
    zipcode: str = Field(pattern=r"^\d{6}$")  # 中国邮编 6 位数字


class OrderItem(BaseModel):
    product: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(gt=0)


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1)
    shipping_address: Address
    items: list[OrderItem] = Field(min_length=1)

    @field_validator("customer_name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("客户名不能为空白字符")
        return v.strip()


class OrderOut(BaseModel):
    customer: str
    city: str
    item_count: int
    total: float


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

router = APIRouter(tags=["request_response"])


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(order: OrderCreate):
    """嵌套模型：Address + list[OrderItem]，field_validator 校验客户名。"""
    total = sum(item.quantity * item.unit_price for item in order.items)
    result = OrderOut(
        customer=order.customer_name,
        city=order.shipping_address.city,
        item_count=len(order.items),
        total=round(total, 2),
    )
    return JSONResponse(content=result.model_dump(), status_code=status.HTTP_201_CREATED)


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="03_nested_models — 嵌套模型")
    app.include_router(router)
    uvicorn.run(app, host="127.0.0.1", port=8000)
