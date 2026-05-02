"""
product-service DB 모델

SQLAlchemy의 선언적(Declarative) 방식으로 테이블을 정의합니다.
클래스 하나 = 테이블 하나입니다.
"""

from datetime import datetime

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
    - created_at/updated_at: func.now() (DB 서버 시간 기준)
      분산 환경에서 각 pod의 로컬 시계(NTP drift)에 의존하지 않도록 통일
    """

    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0", name="ck_products_stock_nonnegative"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
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

    # created_at / updated_at 모두 func.now() (DB 서버 시간 기준) 사용
    # 분산 환경에서 각 pod의 로컬 시계(NTP drift)에 의존하지 않도록
    # DB 서버 시간을 단일 시간 기준으로 통일
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        # func.now()를 onupdate에 사용하면 SQLAlchemy가 UPDATE SET 절에
        # updated_at = now() 를 직접 포함시켜 DB 서버 시간으로 갱신됨
    )
