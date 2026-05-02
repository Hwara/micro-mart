from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

settings = get_settings()

# AsyncEngine: user-service와 동일한 패턴
# pool_size/max_overflow는 운영에서 조정, 개발은 기본값 사용
engine = create_async_engine(
    settings.database_url,
    # debug=True면 실행되는 SQL을 로그로 출력, 운영에서는 SQL 로그 비활성화 (성능 + 보안)
    echo=settings.debug,
    pool_pre_ping=True,  # 연결 유효성 체크 (k8s 재배포 시 stale 커넥션 방지)
    pool_size=10,
    max_overflow=20,
)

# 세션 팩토리: 매번 새로운 AsyncSession을 만들어주는 공장
# expire_on_commit=False: 커밋 후에도 객체 속성에 접근 가능하게 설정
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Redis 클라이언트: decode_responses=True로 bytes→str 자동 변환
# user-service와 동일 Redis 인스턴스이나, 키 네임스페이스로 충돌 방지
redis_client = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=settings.redis_socket_connect_timeout,
    socket_timeout=settings.redis_socket_timeout,
)


async def init_db() -> None:
    """테이블 생성 (개발/테스트용). 운영에서는 Alembic 마이그레이션 사용."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """앱 종료 시 커넥션 풀 정리."""
    await engine.dispose()
    await redis_client.aclose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends용 DB 세션 제공자."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# FastAPI Depends 타입 별칭 (코드 간결화)
DBSession = Annotated[AsyncSession, Depends(get_db)]
