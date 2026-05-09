"""
payment-service 비즈니스 로직.

라우터는 HTTP 경계만 담당하고, 결제/환불 상태 전이와 Chaos Mode 처리는
이 모듈에 모아 컨벤션의 얇은 라우터 원칙을 유지한다.
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException, status
from opentelemetry import metrics
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Payment, PaymentStatus, Refund, RefundStatus
from ..schemas import (
    ErrorResponse,
    PaymentCreateRequest,
    PaymentResponse,
    RefundCreateRequest,
    RefundResponse,
)

log = structlog.get_logger(__name__)

# 설계 문서 관찰성 포인트: 결제 실패율, P95/P99 레이턴시, 결제 금액 히스토그램
meter = metrics.get_meter("payment-service")

payment_counter = meter.create_counter(
    "payment_total",
    description="결제 요청 총 횟수",
    unit="1",
)
payment_approved_counter = meter.create_counter(
    "payment_approved_total",
    description="결제 승인 횟수",
)
payment_rejected_counter = meter.create_counter(
    "payment_rejected_total",
    description="결제 거절 횟수 (Chaos Mode 포함)",
)
payment_amount_histogram = meter.create_histogram(
    "payment_amount_krw",
    description="결제 금액 분포 (원단위)",
    unit="KRW",
)
payment_latency_histogram = meter.create_histogram(
    "payment_processing_latency_ms",
    description="결제 처리 레이턴시 (밀리초)",
    unit="ms",
)
refund_counter = meter.create_counter(
    "refund_total",
    description="환불 요청 총 횟수",
)


def _error(detail: str, code: str | None = None) -> dict[str, str | None]:
    """프로젝트 표준 에러 응답 구조를 유지한다."""
    return ErrorResponse(detail=detail, code=code).model_dump()


async def create_payment_service(
    payload: PaymentCreateRequest,
    db: AsyncSession,
) -> PaymentResponse:
    """
    결제 요청을 승인 또는 거절한다.

    상태 전이는 PENDING -> APPROVED 또는 PENDING -> REJECTED만 허용한다.
    중복 결제는 앱 레벨 선검사와 DB UNIQUE 제약을 함께 사용해 차단한다.
    """
    settings = get_settings()

    payment_counter.add(1)
    payment_amount_histogram.record(payload.amount)

    # DB UNIQUE 제약만으로도 막히지만, 에러 메시지를 명확히 하기 위해 선검사를 유지한다.
    existing = await db.execute(select(Payment).where(Payment.order_id == payload.order_id))
    if existing.scalar_one_or_none():
        log.warning(
            "중복 결제 요청 감지",
            order_id=payload.order_id,
            user_id=payload.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error("이미 처리된 주문의 결제 요청입니다.", "DUPLICATE_PAYMENT"),
        )

    process_start = datetime.now(UTC)

    if settings.chaos_latency_ms > 0:
        log.debug("Chaos 지연 적용", latency_ms=settings.chaos_latency_ms)
        await asyncio.sleep(settings.chaos_latency_ms / 1000)

    # 처리 전 레코드를 먼저 만들어 서버 크래시 시에도 "요청 접수" 기록을 남긴다.
    payment = Payment(
        order_id=payload.order_id,
        user_id=payload.user_id,
        amount=payload.amount,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        log.warning(
            "중복 결제 DB 레벨 차단",
            order_id=payload.order_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error("이미 처리된 주문의 결제 요청입니다.", "DUPLICATE_PAYMENT"),
        ) from e

    # random.random()은 [0.0, 1.0) 균등 분포라 설정값을 그대로 실패 확률로 쓸 수 있다.
    is_chaos_failure = (
        settings.chaos_failure_rate > 0 and random.random() < settings.chaos_failure_rate
    )

    if settings.chaos_db_slowquery:
        await asyncio.sleep(random.uniform(1.0, 3.0))

    if is_chaos_failure:
        payment.status = PaymentStatus.REJECTED
        payment.failure_reason = "CHAOS_FAILURE"
        rejected_at = datetime.now(UTC)
        payment.processed_at = rejected_at
        await db.commit()

        payment_rejected_counter.add(1, {"reason": "chaos"})
        log.warning(
            "결제 거절 (Chaos Mode)",
            order_id=payload.order_id,
            user_id=payload.user_id,
            amount=payload.amount,
            failure_reason="CHAOS_FAILURE",
        )

        latency_ms = (rejected_at - process_start).total_seconds() * 1000
        payment_latency_histogram.record(latency_ms)

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=_error("결제가 거절되었습니다.", "PAYMENT_REJECTED"),
        )

    payment.status = PaymentStatus.APPROVED
    payment.pg_transaction_id = f"PG-{uuid.uuid4().hex[:16].upper()}"

    processed_at = datetime.now(UTC)
    payment.processed_at = processed_at
    await db.commit()
    await db.refresh(payment)

    payment_approved_counter.add(1)

    latency_ms = (processed_at - process_start).total_seconds() * 1000
    payment_latency_histogram.record(latency_ms)

    log.info(
        "결제 승인",
        payment_id=payment.id,
        order_id=payload.order_id,
        user_id=payload.user_id,
        amount=payload.amount,
        pg_transaction_id=payment.pg_transaction_id,
    )

    return PaymentResponse.model_validate(payment)


async def get_payment_service(payment_id: int, db: AsyncSession) -> PaymentResponse:
    """결제 ID로 결제 상태를 조회한다."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 내역을 찾을 수 없습니다.",
        )

    return PaymentResponse.model_validate(payment)


async def create_refund_service(
    payment_id: int,
    payload: RefundCreateRequest,
    db: AsyncSession,
) -> RefundResponse:
    """
    승인된 결제에 대해 부분 또는 전액 환불을 처리한다.

    현재 구현은 기존 동작 보존을 위해 잠금 정책을 추가하지 않는다. 동시 부분 환불의
    초과 환불 가능성은 별도 개선 범위로 둔다.
    """
    refund_counter.add(1)

    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 내역을 찾을 수 없습니다.",
        )

    if payment.status != PaymentStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error(
                f"환불 불가 상태입니다. 현재 상태: {payment.status}",
                "REFUND_NOT_ALLOWED",
            ),
        )

    existing_refunds = await db.execute(
        select(Refund).where(
            Refund.payment_id == payment_id,
            Refund.status == RefundStatus.COMPLETED,
        )
    )
    already_refunded = sum(r.amount for r in existing_refunds.scalars().all())
    refundable = payment.amount - already_refunded

    if payload.amount > refundable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error(
                f"환불 가능 금액을 초과했습니다. 환불 가능: {refundable}원",
                "REFUND_AMOUNT_EXCEEDED",
            ),
        )

    refund = Refund(
        payment_id=payment_id,
        amount=payload.amount,
        reason=payload.reason,
        status=RefundStatus.COMPLETED,
        processed_at=datetime.now(UTC),
    )
    db.add(refund)

    if payload.amount == refundable:
        payment.status = PaymentStatus.REFUNDED

    await db.commit()
    await db.refresh(refund)

    log.info(
        "환불 처리 완료",
        payment_id=payment_id,
        refund_id=refund.id,
        amount=payload.amount,
        order_id=payment.order_id,
    )

    return RefundResponse.model_validate(refund)
