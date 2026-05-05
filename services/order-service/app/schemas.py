"""
order-service 요청/응답 스키마

OrderCreateRequest: 외부 클라이언트 → order-service
OrderResponse: order-service → 클라이언트 (ORM 모델 직접 노출 금지)
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# ── 요청 스키마 ──────────────────────────────────────────


class OrderItemRequest(BaseModel):
    """주문 항목 요청. product_id와 수량만 받고 가격은 product-service에서 조회."""

    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)  # 단건 최대 100개 제한


class OrderCreateRequest(BaseModel):
    """
    주문 생성 요청.
    user_id는 바디가 아닌 X-User-ID 헤더에서 추출 (gateway가 주입, 외부 입력 불신).
    """

    items: list[OrderItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def check_duplicate_product_ids(self) -> "OrderCreateRequest":
        """
        동일 product_id가 두 번 들어오면 deduct_stock이 두 번 호출되나
        products 딕셔너리에는 마지막 값만 남아 총액 계산이 틀어짐.
        입력 단에서 422로 차단.
        """
        product_ids = [item.product_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            duplicates = [pid for pid in set(product_ids) if product_ids.count(pid) > 1]
            raise ValueError(f"중복된 product_id가 포함되어 있습니다: {duplicates}")
        return self


# ── 응답 스키마 ──────────────────────────────────────────


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    unit_price: int
    quantity: int
    discount_amount: int
    subtotal: int
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: int
    payment_id: int | None
    failure_reason: str | None
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    """목록 조회용 — items 제외한 요약 응답."""

    id: int
    status: str
    total_amount: int
    created_at: datetime

    model_config = {"from_attributes": True}
