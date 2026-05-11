"""
order-service 테스트 공통 픽스처

외부 서비스 의존성 격리 전략:
- DB: SQLite in-memory (PostgreSQL 불필요)
- product/payment HTTP 호출: pytest-mock으로 http_clients 함수 직접 mock
  httpx.MockTransport 대신 함수 mock을 선택한 이유:
  - http_clients.py가 URL 조합/헤더/재시도 로직을 캡슐화하므로
    상위 레이어(order_service.py)는 "함수 호출 결과"만 신뢰
  - URL 레벨 mock은 구현 세부사항에 결합되어 리팩토링 취약
"""

import os

import pytest
import pytest_asyncio
from app.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

INTERNAL_TOKEN = "test-internal-token"
TEST_USER_ID = 42
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
_TEST_ENV = {
    "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
    "PRODUCT_SERVICE_URL": "http://mock-product",
    "PAYMENT_SERVICE_URL": "http://mock-payment",
    "NATS_URL": "nats://mock-nats:4222",
    "DATABASE_URL": TEST_DATABASE_URL,
    "OTEL_ENABLED": "false",
}
_ORIGINAL_ENV = {key: os.environ.get(key) for key in _TEST_ENV}

# config.py no longer reads .env files directly, so import-time settings users
# must see test values before app.database/app.main create module-level objects.
for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

from app.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture(scope="session", autouse=True)
def restore_import_time_env():
    """Restore env vars that conftest set before importing app modules."""
    yield
    for key, original in _ORIGINAL_ENV.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """
    모든 테스트 전: 환경변수 설정 + lru_cache 초기화.
    payment-service conftest와 동일 패턴.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("PRODUCT_SERVICE_URL", "http://mock-product")
    monkeypatch.setenv("PAYMENT_SERVICE_URL", "http://mock-payment")
    monkeypatch.setenv("NATS_URL", "nats://mock-nats:4222")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("OTEL_ENABLED", "false")
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """함수마다 독립적인 in-memory DB 엔진."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """각 테스트에 독립적인 DB 세션."""
    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """
    FastAPI 테스트 클라이언트.
    실제 DB 세션을 테스트용 세션으로 교체.
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def user_headers(user_id: int = TEST_USER_ID, role: str = "customer") -> dict:
    """gateway가 주입하는 인증 헤더 헬퍼."""
    return {"X-User-ID": str(user_id), "X-User-Role": role}


def internal_headers() -> dict:
    """내부 서비스 토큰 헤더 헬퍼."""
    return {"X-Internal-Token": INTERNAL_TOKEN}


# ── 외부 서비스 mock 헬퍼 ────────────────────────────────────────


def make_product(
    product_id: int = 1,
    price: int = 10000,
    stock: int = 10,
    version: int = 1,
    is_active: bool = True,
    name: str = "테스트 상품",
) -> dict:
    """테스트용 상품 응답 딕셔너리 생성 헬퍼."""
    return {
        "id": product_id,
        "name": name,
        "price": price,
        "stock": stock,
        "version": version,
        "is_active": is_active,
        "description": None,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }


def make_payment_result(order_id: int, amount: int, payment_id: int = 1) -> dict:
    """테스트용 결제 성공 응답 딕셔너리 생성 헬퍼."""
    return {
        "id": payment_id,
        "order_id": order_id,
        "user_id": TEST_USER_ID,
        "amount": amount,
        "status": "APPROVED",
        "pg_transaction_id": f"PG-TEST-{order_id}",
        "processed_at": "2024-01-01T00:00:00",
    }
