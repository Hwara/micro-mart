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
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.fail_get = False
        self.fail_setex = False
        self.fail_scan = False
        self.fail_delete = False

    async def get(self, key: str) -> str | None:
        if self.fail_get:
            raise RuntimeError("get failed")
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        if self.fail_setex:
            raise RuntimeError("set failed")
        self.values[key] = value
        self.ttls[key] = ttl

    async def delete(self, *keys: str) -> int:
        if self.fail_delete:
            raise RuntimeError("delete failed")
        for key in keys:
            self.deleted.append(key)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 100):
        if self.fail_scan:
            raise RuntimeError("scan failed")
        prefix = (match or "").rstrip("*")
        keys = [key for key in self.values if key.startswith(prefix)]
        return 0, keys


@pytest.fixture(autouse=True)
def clear_settings_cache() -> AsyncGenerator[None, None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
    redis = FakeRedis()
    from app.services import product_service

    monkeypatch.setattr(product_service, "redis_client", redis)
    return redis


@pytest.fixture
async def client(
    db_session: AsyncSession,
    fake_redis: FakeRedis,
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
