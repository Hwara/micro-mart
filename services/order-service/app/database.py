"""
order-service DB 세션 설정

Redis를 사용하지 않으므로 PostgreSQL 설정만 포함.
payment-service 패턴과 동일 구조 유지.
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
                "pool_size": 5,
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
    """개발/테스트 환경에서 테이블 자동 생성 (debug=True 시만 호출)."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """앱 종료 시 커넥션 풀 반납."""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입용 DB 세션 생성기.
    테스트 시 app.dependency_overrides[get_db]로 교체.
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
