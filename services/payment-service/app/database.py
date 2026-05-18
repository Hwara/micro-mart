"""
payment-service 데이터베이스 연결 설정

product-service 패턴 동일하게 유지.
Redis는 payment-service에서 불필요하므로 포함하지 않음.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

settings = get_settings()


def _engine_options(database_url: str, debug: bool) -> dict:
    """
    SQLAlchemy async engine 옵션을 DB 드라이버에 맞게 구성한다.

    SQLite 테스트 엔진은 pool_size/max_overflow를 지원하지 않으므로 제외하고,
    PostgreSQL 운영/로컬 엔진에는 커넥션 풀 옵션을 유지한다.
    """
    options = {
        "echo": debug,
        "pool_pre_ping": True,
    }

    if not database_url.startswith("sqlite"):
        options.update(
            {
                "pool_size": 20,
                "max_overflow": 10,
            }
        )

    return options


engine = create_async_engine(
    settings.database_url,
    **_engine_options(settings.database_url, settings.debug),
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """테이블 생성 (개발/테스트용). 운영에서는 Alembic 마이그레이션 사용."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """앱 종료 시 커넥션 풀 정리."""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입용 DB 세션 생성기.

    commit은 각 route 핸들러에서 명시적으로 호출.
    예외 발생 시 자동 롤백.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


DBSession = Annotated[AsyncSession, Depends(get_db)]
