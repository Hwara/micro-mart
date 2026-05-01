"""
데이터베이스 및 Redis 연결 설정

SQLAlchemy 비동기 엔진과 세션 팩토리를 생성합니다.
각 요청마다 독립적인 세션을 생성하고 요청이 끝나면 자동으로 닫습니다.
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

# ── SQLAlchemy 비동기 엔진 ──
# pool_size: 동시에 유지할 DB 연결 수
# max_overflow: pool_size 초과 시 추가로 허용할 연결 수
# pool_pre_ping: 쿼리 전에 연결이 살아있는지 확인 (연결 끊김 방지)
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.debug,  # debug=True면 실행되는 SQL을 로그로 출력
)

# 세션 팩토리: 매번 새로운 AsyncSession을 만들어주는 공장
# expire_on_commit=False: 커밋 후에도 객체 속성에 접근 가능하게 설정
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Redis 클라이언트 ──
# decode_responses=True: Redis에서 bytes 대신 str로 받음
redis_client = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입(Dependency Injection)용 DB 세션 생성기

    사용법:
        @router.post("/register")
        async def register(db: AsyncSession = Depends(get_db)):
            ...

    with 블록이 끝나면 자동으로 세션이 닫힙니다.
    예외 발생 시 자동으로 롤백됩니다.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
