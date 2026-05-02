"""
user-service DB 모델

SQLAlchemy의 선언적(Declarative) 방식으로 테이블을 정의합니다.
클래스 하나 = 테이블 하나입니다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    모든 모델이 상속받는 베이스 클래스
    SQLAlchemy가 이 클래스를 기준으로 테이블 메타데이터를 관리합니다.
    """

    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)

    # customer | admin
    role: Mapped[str] = mapped_column(String, nullable=False, default="customer")

    # token_version: 이 숫자가 바뀌면 이전에 발급된 모든 Refresh Token이 무효화됨
    # 비밀번호 변경, 강제 로그아웃 등에서 +1 증가
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
