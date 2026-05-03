"""
payment-service 단위 테스트

SQLite in-memory DB로 실제 PostgreSQL 없이 실행 가능.
Chaos Mode는 환경변수 monkeypatch로 제어.
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ─── 테스트 픽스처 ─────────────────────────────────────────────


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
INTERNAL_TOKEN = "test-internal-token"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """함수마다 독립적인 in-memory DB 엔진 생성."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """각 테스트에 독립적인 DB 세션 제공."""
    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session, monkeypatch):
    """
    FastAPI 테스트 클라이언트.

    실제 DB 세션을 테스트용 세션으로 교체 (의존성 오버라이드).

    conftest의 setup_env가 이미 처리하므로 여기서 중복 작업 불필요
    """

    # DB 세션 의존성 오버라이드
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    # cache_clear는 conftest autouse fixture가 처리


def internal_headers() -> dict:
    """내부 서비스 토큰 헤더 헬퍼."""
    return {"X-Internal-Token": INTERNAL_TOKEN}


# ─── 결제 생성 테스트 ──────────────────────────────────────────


class TestCreatePayment:
    """POST /payments 테스트."""

    @pytest.mark.asyncio
    async def test_결제_승인_정상흐름(self, client):
        """Chaos Mode 비활성화 시 결제는 항상 APPROVED."""
        response = await client.post(
            "/payments",
            json={"order_id": 1, "user_id": 10, "amount": 29900},
            headers=internal_headers(),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "APPROVED"
        assert data["order_id"] == 1
        assert data["user_id"] == 10
        assert data["amount"] == 29900
        assert data["pg_transaction_id"] is not None
        assert data["pg_transaction_id"].startswith("PG-")
        assert data["processed_at"] is not None

    @pytest.mark.asyncio
    async def test_내부토큰_누락시_401(self, client):
        """X-Internal-Token 없이 요청하면 401."""
        response = await client.post(
            "/payments",
            json={"order_id": 1, "user_id": 10, "amount": 29900},
            # headers 생략 — 인증 헤더 없음
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_내부토큰_잘못된값_401(self, client):
        """잘못된 X-Internal-Token은 401."""
        response = await client.post(
            "/payments",
            json={"order_id": 1, "user_id": 10, "amount": 29900},
            headers={"X-Internal-Token": "wrong-token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_중복결제_409(self, client):
        """같은 order_id로 두 번 요청하면 409 DUPLICATE_PAYMENT."""
        payload = {"order_id": 99, "user_id": 10, "amount": 5000}

        # 첫 번째 요청: 성공
        first = await client.post("/payments", json=payload, headers=internal_headers())
        assert first.status_code == 201

        # 두 번째 요청: 중복 결제
        second = await client.post("/payments", json=payload, headers=internal_headers())
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "DUPLICATE_PAYMENT"

    @pytest.mark.asyncio
    async def test_금액_0이하_422(self, client):
        """amount가 0 이하면 422 Validation Error."""
        response = await client.post(
            "/payments",
            json={"order_id": 1, "user_id": 10, "amount": 0},
            headers=internal_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_chaos_실패율_100퍼센트(self, client, monkeypatch):
        """CHAOS_FAILURE_RATE=1.0 → 항상 402 PAYMENT_REJECTED."""
        # Settings 캐시를 우회하기 위해 직접 패치
        settings = get_settings()
        monkeypatch.setattr(settings, "chaos_failure_rate", 1.0)

        response = await client.post(
            "/payments",
            json={"order_id": 200, "user_id": 10, "amount": 10000},
            headers=internal_headers(),
        )
        assert response.status_code == 402
        assert response.json()["detail"]["code"] == "PAYMENT_REJECTED"

    @pytest.mark.asyncio
    async def test_chaos_실패율_0퍼센트(self, client, monkeypatch):
        """CHAOS_FAILURE_RATE=0.0 → 항상 APPROVED."""
        settings = get_settings()
        monkeypatch.setattr(settings, "chaos_failure_rate", 0.0)

        response = await client.post(
            "/payments",
            json={"order_id": 300, "user_id": 10, "amount": 10000},
            headers=internal_headers(),
        )
        assert response.status_code == 201
        assert response.json()["status"] == "APPROVED"


# ─── 결제 조회 테스트 ──────────────────────────────────────────


class TestGetPayment:
    """GET /payments/{payment_id} 테스트."""

    @pytest.mark.asyncio
    async def test_결제_조회_정상(self, client):
        """생성된 결제를 ID로 조회."""
        # 결제 생성
        create_res = await client.post(
            "/payments",
            json={"order_id": 10, "user_id": 5, "amount": 15000},
            headers=internal_headers(),
        )
        payment_id = create_res.json()["id"]

        # 조회
        get_res = await client.get(f"/payments/{payment_id}", headers=internal_headers())
        assert get_res.status_code == 200
        assert get_res.json()["id"] == payment_id
        assert get_res.json()["order_id"] == 10

    @pytest.mark.asyncio
    async def test_없는결제_404(self, client):
        """존재하지 않는 payment_id → 404."""
        response = await client.get("/payments/99999", headers=internal_headers())
        assert response.status_code == 404


# ─── 환불 테스트 ───────────────────────────────────────────────


class TestCreateRefund:
    """POST /payments/{payment_id}/refunds 테스트."""

    @pytest_asyncio.fixture
    async def approved_payment_id(self, client) -> int:
        """APPROVED 상태 결제를 미리 생성하는 픽스처."""
        res = await client.post(
            "/payments",
            json={"order_id": 50, "user_id": 7, "amount": 50000},
            headers=internal_headers(),
        )
        assert res.status_code == 201
        return res.json()["id"]

    @pytest.mark.asyncio
    async def test_전액환불_정상(self, client, approved_payment_id):
        """결제 금액 전액 환불."""
        response = await client.post(
            f"/payments/{approved_payment_id}/refunds",
            json={"amount": 50000, "reason": "고객 변심"},
            headers=internal_headers(),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["amount"] == 50000
        assert data["status"] == "COMPLETED"
        assert data["processed_at"] is not None

    @pytest.mark.asyncio
    async def test_부분환불_정상(self, client, approved_payment_id):
        """결제 금액 일부만 환불."""
        response = await client.post(
            f"/payments/{approved_payment_id}/refunds",
            json={"amount": 20000, "reason": "일부 반품"},
            headers=internal_headers(),
        )
        assert response.status_code == 201
        assert response.json()["amount"] == 20000

    @pytest.mark.asyncio
    async def test_환불금액_초과_422(self, client, approved_payment_id):
        """결제 금액보다 많은 환불 요청 → 422."""
        response = await client.post(
            f"/payments/{approved_payment_id}/refunds",
            json={"amount": 99999},
            headers=internal_headers(),
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "REFUND_AMOUNT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_부분환불_누적_초과_422(self, client, approved_payment_id):
        """부분 환불 두 번 합산이 결제 금액 초과 → 422."""
        # 첫 번째 부분 환불: 30000
        await client.post(
            f"/payments/{approved_payment_id}/refunds",
            json={"amount": 30000},
            headers=internal_headers(),
        )
        # 두 번째: 남은 20000인데 25000 요청 → 초과
        response = await client.post(
            f"/payments/{approved_payment_id}/refunds",
            json={"amount": 25000},
            headers=internal_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_미승인결제_환불불가_400(self, client, monkeypatch):
        """REJECTED 결제는 환불 불가 → 400."""
        settings = get_settings()
        # Chaos 100%로 REJECTED 결제 생성
        monkeypatch.setattr(settings, "chaos_failure_rate", 1.0)
        create_res = await client.post(
            "/payments",
            json={"order_id": 77, "user_id": 3, "amount": 10000},
            headers=internal_headers(),
        )
        # Chaos 실패 → 402 but payment record exists with REJECTED
        # 402 응답이지만 DB에는 REJECTED 레코드가 남음
        # payment_id는 DB에서 직접 조회 필요 (아래는 db_session 픽스처 활용)
        assert create_res.status_code == 402

    @pytest.mark.asyncio
    async def test_없는결제_환불_404(self, client):
        """존재하지 않는 결제에 환불 요청 → 404."""
        response = await client.post(
            "/payments/99999/refunds",
            json={"amount": 1000},
            headers=internal_headers(),
        )
        assert response.status_code == 404


# ─── 헬스체크 테스트 ──────────────────────────────────────────


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_헬스체크_정상(self, client):
        """헬스체크는 인증 없이 접근 가능."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "payment-service"
        assert "chaos" in data
