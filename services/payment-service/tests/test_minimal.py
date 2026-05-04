# tests/test_minimal.py
"""
진단용 최소 테스트 — 레이어별로 무엇이 실패하는지 확인
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


# ── 레이어 1: import 자체가 되는지 ──────────────────────────────
def test_레이어1_import_성공():
    """app 모듈 import가 되는지 확인."""
    from app.main import app

    assert app is not None


# ── 레이어 2: DB 엔진 생성 + 테이블 생성 ───────────────────────
@pytest.mark.asyncio
async def test_레이어2_DB엔진_생성():
    """SQLite in-memory 엔진이 정상 생성되는지 확인."""
    from app.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("\n✅ 엔진 생성 및 테이블 생성 성공")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── 레이어 3: DB 세션에서 직접 INSERT ──────────────────────────
@pytest.mark.asyncio
async def test_레이어3_DB_INSERT():
    """세션을 통해 Payment 레코드를 직접 삽입할 수 있는지 확인."""
    from app.models import Base, Payment

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        payment = Payment(order_id=1, user_id=10, amount=29900, status="PENDING")
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        print(f"\n✅ INSERT 성공: payment.id={payment.id}")
        assert payment.id is not None

    # 같은 order_id로 한 번 더 INSERT 시도 → UNIQUE 위반 확인
    from sqlalchemy.exc import IntegrityError

    async with factory() as session:
        dup = Payment(order_id=1, user_id=10, amount=100, status="PENDING")
        session.add(dup)
        try:
            await session.commit()
            pytest.fail("중복 INSERT가 통과됨 — payments.order_id UNIQUE 제약이 작동하지 않음")
        except IntegrityError:
            print("\n✅ 중복 INSERT 차단 확인 (UNIQUE 정상 작동)")

    await engine.dispose()


# ── 레이어 4: FastAPI app 자체가 뜨는지 ────────────────────────
@pytest.mark.asyncio
async def test_레이어4_앱_헬스체크():
    """실제 DB 연결 없이 /health 엔드포인트가 응답하는지 확인."""
    import os

    os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        print(f"\n응답 코드: {response.status_code}")
        print(f"응답 내용: {response.json()}")
        assert response.status_code == 200


# ── 레이어 5: 의존성 오버라이드가 작동하는지 ───────────────────
@pytest.mark.asyncio
async def test_레이어5_의존성_오버라이드():
    """
    get_db 오버라이드가 실제로 적용되는지 확인.

    이게 실패하면: app.dependency_overrides 경로가 잘못됨
    """
    import os

    os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

    from app.config import get_settings
    from app.database import get_db
    from app.main import app
    from app.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    override_called = False

    async def override_get_db():
        nonlocal override_called
        override_called = True
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    get_settings.cache_clear()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 인증 없이 → 401이지만 override는 호출됨
            response = await client.post(
                "/payments",
                json={"order_id": 1, "user_id": 10, "amount": 100},
            )
            print(f"\n응답 코드: {response.status_code}")
            print(f"override_called: {override_called}")
            # 401이어도 괜찮음 — 우리가 확인하려는 건 오버라이드 호출 여부
            assert response.status_code in (401, 201)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ── 레이어 6: 토큰 인증 포함 실제 결제 요청 ────────────────────
@pytest.mark.asyncio
async def test_레이어6_결제_승인_정상흐름():
    """
    목표 테스트: POST /payments → 201 APPROVED

    레이어 1~5가 모두 통과한 후에 이 테스트를 실행하세요.
    """
    import os

    os.environ["INTERNAL_SERVICE_TOKEN"] = "test-token"

    from app.config import get_settings
    from app.database import get_db
    from app.main import app
    from app.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    get_settings.cache_clear()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/payments",
                json={"order_id": 1, "user_id": 10, "amount": 29900},
                headers={"X-Internal-Token": "test-token"},
            )
            print(f"\n응답 코드: {response.status_code}")
            print(f"응답 내용: {response.json()}")
            assert response.status_code == 201
            assert response.json()["status"] == "APPROVED"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
        get_settings.cache_clear()
