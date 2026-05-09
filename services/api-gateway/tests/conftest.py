"""
api-gateway 테스트 공통 픽스처

핵심 설계:
1. RS256 키쌍을 테스트 실행 시 동적 생성 → 실제 user-service 불필요
2. JWKS Mock은 respx로 httpx 요청 인터셉트 → 네트워크 없이 테스트
3. JWKSCache를 각 테스트 전 초기화 → 테스트 간 캐시 오염 방지
4. 환경변수 원본 복원은 payment-service conftest 패턴 그대로 적용
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import time

import pytest
import pytest_asyncio
from app.config import get_settings
from app.middleware.auth import jwks_cache
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

# ── 테스트용 RS256 키쌍 (모듈 레벨 1회 생성) ─────────────────────
# 매 테스트마다 생성하면 느리므로 모듈 레벨에서 한 번만 생성.
# 동일한 키쌍을 conftest 전체에서 공유.
_TEST_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key()

# kid: 테스트 환경에서 고정 값 사용
TEST_KID = "test-key-1"


def make_jwks_response() -> dict:
    """
    테스트용 JWKS 응답 생성.

    실제 user-service /auth/jwks 응답 형식과 동일하게 구성.
    cryptography 라이브러리의 public_bytes로 PEM 추출 후 JWK 형식 변환은
    PyJWT의 RSAAlgorithm.to_jwk()를 활용.
    """
    import json as _json

    from jwt.algorithms import RSAAlgorithm

    jwk_str = RSAAlgorithm.to_jwk(_TEST_PUBLIC_KEY)
    jwk_dict = _json.loads(jwk_str)
    jwk_dict["kid"] = TEST_KID
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"
    return {"keys": [jwk_dict]}


def make_access_token(
    sub: str = "42",
    role: str = "customer",
    exp_offset: int = 900,  # 기본 15분 유효
) -> str:
    """
    테스트용 RS256 Access Token 생성.

    sub: user_id (str) — JWT 표준 claim
    role: 사용자 역할
    exp_offset: 현재 시각 기준 만료 시간(초). 음수면 이미 만료된 토큰.
    """
    import jwt

    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + exp_offset,
    }
    private_key_pem = _TEST_PRIVATE_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        payload,
        private_key_pem,
        algorithm="RS256",
        headers={"kid": TEST_KID},
    )


@pytest.fixture(autouse=True)
def setup_env():
    """
    모든 테스트 전: 환경변수 설정 + settings 캐시 초기화
    모든 테스트 후: 캐시 및 JWKS 캐시 초기화

    payment-service conftest와 동일한 패턴.
    api-gateway는 JWKS 캐시 상태도 격리해야 하므로 추가.
    """
    original_jwks = os.environ.get("JWKS_URL")
    original_algo = os.environ.get("JWT_ALGORITHM")
    original_audience = os.environ.get("JWT_AUDIENCE")
    original_otel_enabled = os.environ.get("OTEL_ENABLED")

    get_settings.cache_clear()
    os.environ["JWKS_URL"] = "http://user-service:8000/auth/jwks"
    os.environ["JWT_ALGORITHM"] = "RS256"
    os.environ["JWT_AUDIENCE"] = ""  # audience 검증 생략
    os.environ["OTEL_ENABLED"] = "false"

    # JWKS 캐시 초기화 — 이전 테스트의 공개키가 남아있으면 검증 결과가 오염됨
    jwks_cache._keys = {}
    jwks_cache._fetched_at = 0.0

    yield

    get_settings.cache_clear()
    jwks_cache._keys = {}
    jwks_cache._fetched_at = 0.0

    # 환경변수 원본 복원
    for key, original in [
        ("JWKS_URL", original_jwks),
        ("JWT_ALGORITHM", original_algo),
        ("JWT_AUDIENCE", original_audience),
        ("OTEL_ENABLED", original_otel_enabled),
    ]:
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


@pytest_asyncio.fixture
async def client():
    """
    FastAPI 테스트 클라이언트.

    respx는 별도로 각 테스트에서 컨텍스트 매니저로 사용.
    """
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def auth_headers(token: str) -> dict:
    """Bearer 토큰 헤더 헬퍼."""
    return {"Authorization": f"Bearer {token}"}
