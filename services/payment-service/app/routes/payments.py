"""
payment-service 라우터

결제/환불 내부 API의 HTTP 경계를 담당.
모든 엔드포인트는 내부 서비스 전용 (X-Internal-Token 필수).
"""

from fastapi import APIRouter, Depends, status

from ..database import DBSession
from ..dependencies import verify_internal_service
from ..schemas import (
    ErrorResponse,
    PaymentCreateRequest,
    PaymentResponse,
    RefundCreateRequest,
    RefundResponse,
)
from ..services.payment_service import (
    create_payment_service,
    create_refund_service,
    get_payment_service,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "중복 결제"},
        402: {"model": ErrorResponse, "description": "결제 거절 (Chaos Mode 포함)"},
    },
    dependencies=[Depends(verify_internal_service)],
)
async def create_payment(
    payload: PaymentCreateRequest,
    db: DBSession,
) -> PaymentResponse:
    """결제 요청 처리 (order-service 전용 내부 API)."""
    return await create_payment_service(payload=payload, db=db)


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    dependencies=[Depends(verify_internal_service)],
)
async def get_payment(payment_id: int, db: DBSession) -> PaymentResponse:
    """결제 상태 조회 (order-service 전용 내부 API)."""
    return await get_payment_service(payment_id=payment_id, db=db)


@router.post(
    "/{payment_id}/refunds",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "환불 불가 상태"},
        422: {"model": ErrorResponse, "description": "환불 금액 초과"},
    },
    dependencies=[Depends(verify_internal_service)],
)
async def create_refund(
    payment_id: int,
    payload: RefundCreateRequest,
    db: DBSession,
) -> RefundResponse:
    """환불 요청 처리 (order-service 전용 내부 API)."""
    return await create_refund_service(payment_id=payment_id, payload=payload, db=db)
