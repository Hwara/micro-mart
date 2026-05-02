from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    """
    products 테이블

    설계 결정:
    - price: Integer → 원단위 정수
    - stock: Integer → 음수 방지는 DB CHECK 제약 + 앱 레벨 이중 방어
    - version: 낙관적 잠금용. 재고 차감 시 WHERE version = :expected 로 충돌 감지
    - is_active: 물리 삭제 대신 소프트 삭제 → 주문 이력 보존 가능
    - created_at/updated_at: timezone-aware UTC 저장
    """

    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0", name="ck_products_stock_nonnegative"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        # DB 레벨에서 음수 재고 방지 (앱 레벨 검증의 마지막 방어선)
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="낙관적 잠금용 버전 번호. 재고 차감마다 +1"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )
