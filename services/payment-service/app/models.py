"""
payment-service DB 모델

payments.order_id에 UNIQUE 제약을 두어 중복 결제를 DB 레벨에서 차단.
refunds는 별도 테이블로 분리 → 부분 환불 확장 가능.
"""

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PaymentStatus(str, enum.Enum):
    """
    결제 상태 전이:
    PENDING → APPROVED (PG 승인)
    PENDING → REJECTED (PG 거절 또는 Chaos Mode)
    APPROVED → REFUNDED (환불 완료)
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"


class RefundStatus(str, enum.Enum):
    """
    환불 상태 전이:
    PENDING → COMPLETED (환불 처리 완료)
    PENDING → FAILED (환불 실패)
    """

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Payment(Base):
    """
    payments 테이블

    설계 결정:
    - order_id UNIQUE: 네트워크 재시도로 인한 중복 결제 DB 레벨 차단 (멱등성 보장)
    - processed_at 분리: created_at(레코드 생성) vs processed_at(PG 응답) 차이 = 결제 레이턴시
    - pg_transaction_id: 실 PG 연동 시 외부 트랜잭션 ID 추적용 (현재는 UUID 시뮬레이션)
    - amount Integer: 부동소수점 오차 방지, 원단위 정수 저장
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # order-service orders.id 논리적 참조. UNIQUE → 중복 결제 DB 레벨 차단
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    # user-service users.id 논리적 참조
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PaymentStatus.PENDING)
    pg_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # processed_at: 실제 PG 승인/거절 처리 완료 시각 (created_at과 차이 = 결제 레이턴시)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 동일 DB 내 물리적 FK 허용 (refunds → payments)
    refunds: Mapped[list["Refund"]] = relationship("Refund", back_populates="payment")


class Refund(Base):
    """
    refunds 테이블

    별도 테이블 분리 이유:
    - 부분 환불 지원 (amount ≤ payments.amount)
    - 환불 이력 누적 가능 (1:N)
    - processed_at으로 환불 처리 레이턴시 관찰
    """

    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 동일 DB 내 물리적 FK
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RefundStatus.PENDING)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment: Mapped["Payment"] = relationship("Payment", back_populates="refunds")
