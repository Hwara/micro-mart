"""
order-service ORM 모델

orders: Saga 오케스트레이션 상태 추적의 핵심.
  - saga_status: 복구 배치 잡이 스캔할 기준 필드
  - stock_deducted: 결제 실패 시 보상 트랜잭션 실행 여부 판단

order_items: 주문 시점 상품 스냅샷 저장 (불변 데이터, updated_at 없음).

서비스 간 참조(user_id, product_id, payment_id)는 물리적 FK 금지.
order_items.order_id만 동일 DB 내 물리적 FK 허용.
"""

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class BigIntegerType(TypeDecorator):
    """
    PostgreSQL: BIGINT, SQLite: INTEGER로 렌더링.
    payment-service와 동일한 패턴 — SQLite 테스트 환경 호환.
    """

    impl = BigInteger
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            from sqlalchemy import Integer as IntType

            return dialect.type_descriptor(IntType())
        return dialect.type_descriptor(BigInteger())


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    """
    주문 상태 전이 (ERD_structure.md 기준):
    PENDING → STOCK_DEDUCTED → PAYMENT_REQUESTED → COMPLETED
    PENDING → FAILED (재고 부족)
    PAYMENT_REQUESTED → FAILED (결제 실패 + 롤백 완료)
    """

    PENDING = "PENDING"
    STOCK_DEDUCTED = "STOCK_DEDUCTED"
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SagaStatus(str, enum.Enum):
    """
    Saga 오케스트레이션 상태 전이 (ERD_structure.md 기준):
    STARTED → STOCK_DEDUCTED → PAYMENT_REQUESTED → COMPLETED
    PAYMENT_REQUESTED → STOCK_ROLLBACK_NEEDED → STOCK_ROLLED_BACK → FAILED
    STARTED → FAILED (재고 차감 실패)
    """

    STARTED = "STARTED"
    STOCK_DEDUCTED = "STOCK_DEDUCTED"
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    COMPLETED = "COMPLETED"
    STOCK_ROLLBACK_NEEDED = "STOCK_ROLLBACK_NEEDED"
    STOCK_ROLLED_BACK = "STOCK_ROLLED_BACK"
    FAILED = "FAILED"


class Order(Base):
    """
    orders 테이블

    설계 결정:
    - saga_status + stock_deducted 분리: 서버 재시작·장애 시 DB만 보고 복구 판단 가능
    - total_amount 스냅샷: 상품 가격 변경 후에도 원래 결제 금액 보존
    - failure_reason: Loki 메트릭 레이블용, 실패 원인 분류
    - payment_id: 결제 완료 후에만 채워짐 (NULLABLE)
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigIntegerType, primary_key=True, autoincrement=True)
    # user-service users.id 논리적 참조 (물리적 FK 금지)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OrderStatus.PENDING)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # payment-service payments.id 논리적 참조. 결제 완료 후 기입
    payment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Saga 상태 추적 — 복구 배치 잡이 STOCK_ROLLBACK_NEEDED 행을 스캔
    saga_status: Mapped[str] = mapped_column(String(30), nullable=False, default=SagaStatus.STARTED)
    # 재고 차감 완료 여부 — 결제 실패 시 보상 트랜잭션 실행 판단 근거
    stock_deducted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 동일 DB 내 물리적 FK 허용
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    """
    order_items 테이블

    설계 결정:
    - 불변 데이터 → updated_at 없음 (의도적 제외, ERD_structure.md 명시)
    - product_name, unit_price 스냅샷: 상품 삭제·가격 변경 후에도 CS·정산·환불 가능
    - subtotal 명시적 저장: 할인 적용 후 실결제액이 수식과 다를 수 있어 저장
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigIntegerType, primary_key=True, autoincrement=True)
    # 동일 DB 내 물리적 FK
    order_id: Mapped[int] = mapped_column(
        BigIntegerType, ForeignKey("orders.id"), nullable=False, index=True
    )
    # product-service products.id 논리적 참조
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 주문 시점 상품명 스냅샷
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 주문 시점 단가 스냅샷 (정산·환불 기준가)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped["Order"] = relationship("Order", back_populates="items")
