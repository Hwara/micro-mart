import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(REPO_ROOT))

TEST_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/0",
    "INTERNAL_SERVICE_TOKEN": "test-internal-token",
    "PRODUCT_CACHE_TTL": "60",
    "DEFAULT_PAGE_SIZE": "10",
    "MAX_PAGE_SIZE": "100",
    "OTEL_ENABLED": "false",
}
for key, value in TEST_ENV.items():
    os.environ[key] = value

from app.config import get_settings

get_settings.cache_clear()

from app.database import get_db
from app.main import app
from app.models import Base


class FakeRedis:
    """Small async Redis fake for cache-aside tests."""

    def __init__(self) -> None:
        """캐시 값, TTL, 삭제 기록과 실패 플래그를 메모리에 준비한다."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.fail_get = False
        self.fail_setex = False
        self.fail_scan = False
        self.fail_delete = False

    async def get(self, key: str) -> str | None:
        """캐시 조회 성공, miss, Redis get 실패를 모두 흉내 낸다."""
        if self.fail_get:
            raise RuntimeError("get failed")
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """캐시 저장 값과 TTL을 기록하거나 설정된 실패를 발생시킨다."""
        if self.fail_setex:
            raise RuntimeError("set failed")
        self.values[key] = value
        self.ttls[key] = ttl

    async def delete(self, *keys: str) -> int:
        """삭제된 key를 기록하고 캐시 저장소에서 제거한다."""
        if self.fail_delete:
            raise RuntimeError("delete failed")
        for key in keys:
            self.deleted.append(key)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 100):
        """목록 캐시 무효화가 사용하는 SCAN 명령을 prefix matching으로 흉내 낸다."""
        if self.fail_scan:
            raise RuntimeError("scan failed")
        prefix = (match or "").rstrip("*")
        keys = [key for key in self.values if key.startswith(prefix)]
        return 0, keys


@pytest.fixture(autouse=True)
def clear_settings_cache() -> AsyncGenerator[None, None]:
    """환경변수 기반 Settings cache가 테스트 간 공유되지 않도록 초기화한다."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """각 테스트마다 독립적인 async SQLite schema와 session을 제공한다."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """product service의 Redis client를 메모리 fake로 교체한다."""
    redis = FakeRedis()
    from app.services import product_service

    monkeypatch.setattr(product_service, "redis_client", redis)
    return redis


@pytest.fixture
async def client(
    db_session: AsyncSession,
    fake_redis: FakeRedis,
) -> AsyncGenerator[AsyncClient, None]:
    """DB와 Redis 의존성을 fake로 바꾼 FastAPI async client를 제공한다."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        """FastAPI route가 테스트 DB session을 사용하도록 주입한다."""
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
