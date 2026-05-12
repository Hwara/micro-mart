import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
sys.path.insert(0, str(REPO_ROOT))


def _make_test_keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_key = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_key


JWT_PRIVATE_KEY, JWT_PUBLIC_KEY = _make_test_keys()
TEST_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_PRIVATE_KEY": JWT_PRIVATE_KEY,
    "JWT_PUBLIC_KEY": JWT_PUBLIC_KEY,
    "JWT_PRIVATE_KEY_FILE": "",
    "JWT_PUBLIC_KEY_FILE": "",
    "JWT_ALGORITHM": "RS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "15",
    "REFRESH_TOKEN_EXPIRE_DAYS": "7",
    "OTEL_ENABLED": "false",
}
for key, value in TEST_ENV.items():
    os.environ[key] = value

from app.config import get_settings

get_settings.cache_clear()

from app.database import get_db
from app.main import app
from app.models import Base


class FakePipeline:
    """Async Redis pipeline subset used by refresh token helpers."""

    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.operations: list[tuple[str, tuple]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.operations.append(("setex", (key, ttl, value)))

    def delete(self, *keys: str) -> None:
        self.operations.append(("delete", keys))

    async def execute(self) -> None:
        for operation, args in self.operations:
            if operation == "setex":
                key, ttl, value = args
                await self.redis.setex(key, ttl, value)
            elif operation == "delete":
                await self.redis.delete(*args)


class FakeRedis:
    """Small async Redis fake with TTL and scan support for auth tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += int(key in self.values)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return deleted

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def scan_iter(self, pattern: str):
        prefix = pattern.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


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
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "redis_client", redis)
    return redis


@pytest.fixture
async def client(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
