"""
payment-service 라우터

결제 승인/거절 시뮬레이션, Chaos Mode, 환불 처리를 담당.
모든 엔드포인트는 내부 서비스 전용 (X-Internal-Token 필수).
"""

import asyncio
import random
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from opentelemetry import metrics
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..database import DBSession
from ..dependencies import verify_internal_service
from ..models import Payment, PaymentStatus, Refund, RefundStatus
from ..schemas import (
    ErrorResponse,
    PaymentCreateRequest,
    PaymentResponse,
    RefundCreateRequest,
    RefundResponse,
)

router = APIRouter(prefix="/payments", tags=["payments"])
log = structlog.get_logger(__name__)
settings = get_settings()

# ─── 관찰성 메트릭 ────────────────────────────────────────────────
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

# 결제 금액 히스토그램 → Grafana에서 P95/P99 레이턴시와 함께 분석
payment_amount_histogram = meter.create_histogram(
    "payment_amount_krw",
    description="결제 금액 분포 (원단위)",
    unit="KRW",
)

# 결제 처리 레이턴시 히스토그램 (created_at → processed_at 차이)
payment_latency_histogram = meter.create_histogram(
    "payment_processing_latency_ms",
    description="결제 처리 레이턴시 (밀리초)",
    unit="ms",
)

refund_counter = meter.create_counter(
    "refund_total",
    description="환불 요청 총 횟수",
)


# ─── 엔드포인트 ──────────────────────────────────────────────────


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
    """
    결제 요청 처리 (order-service 전용 내부 API).

    처리 흐름:
    1. 중복 결제 선검사 (order_id 중복 조회)
    2. Chaos Mode 지연 적용 (CHAOS_LATENCY_MS)
    3. PENDING 상태로 Payment 레코드 생성
    4. Chaos Mode 실패율 평가 (CHAOS_FAILURE_RATE)
    5. 승인/거절 결과 저장 후 응답

    멱등성:
    - order_id UNIQUE 제약으로 DB 레벨 중복 방지
    - 앱 레벨 선검사로 409 응답 코드 명확화
    """
    payment_counter.add(1)
    payment_amount_histogram.record(payload.amount)

    # ① 중복 결제 선검사
    # DB UNIQUE 제약만으로도 막히지만, 에러 메시지를 명확히 하기 위해 앱 레벨 검사 추가
    existing = await db.execute(select(Payment).where(Payment.order_id == payload.order_id))
    if existing.scalar_one_or_none():
        log.warning(
            "중복 결제 요청 감지",
            order_id=payload.order_id,
            user_id=payload.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                detail="이미 처리된 주문의 결제 요청입니다.",
                code="DUPLICATE_PAYMENT",
            ).model_dump(),
        )

    # ② Chaos Mode 지연 (asyncio.sleep으로 비동기 처리 — 다른 요청 블로킹 없음)
    if settings.chaos_latency_ms > 0:
        log.debug("Chaos 지연 적용", latency_ms=settings.chaos_latency_ms)
        await asyncio.sleep(settings.chaos_latency_ms / 1000)

    # ③ PENDING 상태로 레코드 선생성
    # 처리 전 레코드를 먼저 만들어 놓으면: 서버 크래시 시에도 "요청 접수" 기록이 남음
    payment = Payment(
        order_id=payload.order_id,
        user_id=payload.user_id,
        amount=payload.amount,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    try:
        await db.flush()  # ID 채번, UNIQUE 충돌은 여기서 IntegrityError 발생
    except IntegrityError as e:
        await db.rollback()
        log.warning(
            "중복 결제 DB 레벨 차단",
            order_id=payload.order_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                detail="이미 처리된 주문의 결제 요청입니다.",
                code="DUPLICATE_PAYMENT",
            ).model_dump(),
        ) from e

    # ④ Chaos Mode 실패율 평가
    # random.random()은 [0.0, 1.0) 균등 분포 → chaos_failure_rate 이하면 강제 거절
    is_chaos_failure = (
        settings.chaos_failure_rate > 0 and random.random() < settings.chaos_failure_rate
    )

    process_start = datetime.now(UTC)
    processed_at = datetime.now(UTC)

    # ⑤ Chaos DB 슬로우쿼리 시뮬레이션
    if settings.chaos_db_slowquery:
        # 실제 슬로우쿼리 대신 sleep으로 시뮬레이션
        await asyncio.sleep(random.uniform(1.0, 3.0))

    # ⑥ 승인 또는 거절 처리
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

        # 레이턴시 메트릭 기록
        latency_ms = (rejected_at - process_start).total_seconds() * 1000
        payment_latency_histogram.record(latency_ms)

        # 402 Payment Required: 결제 거절을 표현하는 가장 적합한 HTTP 상태 코드
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=ErrorResponse(
                detail="결제가 거절되었습니다.",
                code="PAYMENT_REJECTED",
            ).model_dump(),
        )

    # 승인 처리: PG 트랜잭션 ID는 UUID로 시뮬레이션
    payment.status = PaymentStatus.APPROVED
    payment.pg_transaction_id = f"PG-{uuid.uuid4().hex[:16].upper()}"
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


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    dependencies=[Depends(verify_internal_service)],
)
async def get_payment(payment_id: int, db: DBSession) -> PaymentResponse:
    """결제 상태 조회 (order-service 전용 내부 API)."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 내역을 찾을 수 없습니다.",
        )

    return PaymentResponse.model_validate(payment)


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
    """
    환불 요청 처리 (order-service 전용 내부 API).

    부분 환불 지원:
    - payload.amount ≤ payments.amount 검증
    - refunds 테이블에 이력 누적 (여러 번 부분 환불 가능)

    환불 가능 조건:
    - payments.status == APPROVED (PENDING/REJECTED/REFUNDED는 환불 불가)
    """
    refund_counter.add(1)

    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="결제 내역을 찾을 수 없습니다.",
        )

    # APPROVED 상태만 환불 가능
    if payment.status != PaymentStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                detail=f"환불 불가 상태입니다. 현재 상태: {payment.status}",
                code="REFUND_NOT_ALLOWED",
            ).model_dump(),
        )

    # 환불 금액 초과 검증 (부분 환불 고려: 기존 환불 합산)
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
            detail=ErrorResponse(
                detail=f"환불 가능 금액을 초과했습니다. 환불 가능: {refundable}원",
                code="REFUND_AMOUNT_EXCEEDED",
            ).model_dump(),
        )

    # 환불 레코드 생성 및 처리
    refund = Refund(
        payment_id=payment_id,
        amount=payload.amount,
        reason=payload.reason,
        status=RefundStatus.COMPLETED,
        processed_at=datetime.now(UTC),
    )
    db.add(refund)

    # 전액 환불이면 payment 상태도 REFUNDED로 변경
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
