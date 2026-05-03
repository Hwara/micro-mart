"""
payment-service 요청/응답 스키마

내부 API(order-service 호출)와 외부 API(환불 조회 등)를 구분.
ORM 모델을 직접 응답으로 노출하지 않음.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── 결제 요청/응답 ──────────────────────────────────────────────


class PaymentCreateRequest(BaseModel):
    """
    결제 요청 (order-service → payment-service 내부 호출).

    order_id, user_id, amount는 order-service가 검증한 값을 신뢰.
    payment-service는 헤더(X-Internal-Token)로 호출 출처만 검증.
    """

    order_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    amount: int = Field(gt=0, description="결제 금액 (원단위 정수)")


class PaymentResponse(BaseModel):
    """결제 결과 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    user_id: int
    amount: int
    status: str
    pg_transaction_id: str | None
    failure_reason: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── 환불 요청/응답 ──────────────────────────────────────────────


class RefundCreateRequest(BaseModel):
    """환불 요청."""

    amount: int = Field(gt=0, description="환불 금액 (원단위, 부분 환불 가능)")
    reason: str | None = Field(None, max_length=500)


class RefundResponse(BaseModel):
    """환불 결과 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    amount: int
    reason: str | None
    status: str
    processed_at: datetime | None
    created_at: datetime


# ── 공통 에러 ──────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """에러 응답 표준 형식 (product-service와 동일 구조 유지)."""

    detail: str
    code: str | None = None
