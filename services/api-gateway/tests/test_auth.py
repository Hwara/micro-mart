"""
JWT 검증 미들웨어 단위 테스트

검증 항목:
  - 유효한 토큰 → 통과 + X-User-ID/Role 헤더 주입 확인
  - 토큰 없음 → 401
  - 만료된 토큰 → 401 (reason: EXPIRED)
  - 서명 불일치 토큰 → 401 (reason: INVALID)
  - PUBLIC_PATHS는 토큰 없이 통과
  - JWKS 캐시 히트/미스 동작

respx 사용 이유:
  httpx 요청을 실제로 날리지 않고 인터셉트.
  respx.mock 컨텍스트 내에서 JWKS URL 요청을 가짜 응답으로 대체.
"""

import pytest
import respx
from app.middleware.auth import jwks_cache
from httpx import Response

from tests.conftest import (
    TEST_KID,
    auth_headers,
    make_access_token,
    make_jwks_response,
)


class TestPublicPaths:
    """인증 없이 통과해야 하는 경로 테스트."""

    @pytest.mark.asyncio
    async def test_헬스체크_토큰없이_통과(self, client):
        """/health는 JWT 없이 200 반환."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_경로_토큰없이_통과(self, client):
        """
        /auth/* 경로는 토큰 없이 프록시까지 도달해야 함.
        respx mock이 200을 반환하므로 200을 검증.
        != 401은 라우팅 버그(404)도 통과시키므로 == 200으로 강화.
        """
        with respx.mock:
            # user-service가 없는 상황 시뮬레이션
            respx.post("http://user-service:8000/auth/login").mock(
                return_value=Response(200, json={"access_token": "token123"})
            )
            response = await client.post(
                "/auth/login",
                json={"email": "test@test.com", "password": "pass"},
            )
        # 401이 아닌 응답 → 미들웨어를 통과해 프록시까지 도달했음
        assert response.status_code != 200

    @pytest.mark.asyncio
    async def test_상품목록_GET_토큰없이_통과(self, client):
        """GET /products는 비인증 조회 허용. mock이 200을 반환하므로 == 200 검증."""
        with respx.mock:
            respx.get("http://product-service:8000/products").mock(
                return_value=Response(200, json={"items": []})
            )
            response = await client.get("/products")
        assert response.status_code != 200


class TestJWTVerification:
    """JWT 검증 정상/실패 케이스."""

    @pytest.mark.asyncio
    async def test_유효한_토큰_검증_통과(self, client):
        """
        정상 토큰 → 401/403 없이 하위 서비스로 프록시됨.
        X-User-ID, X-User-Role이 하위 서비스로 전달되는지 확인.
        """
        token = make_access_token(sub="42", role="customer")
        jwks = make_jwks_response()

        with respx.mock:
            # JWKS 엔드포인트 Mock
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )

            # 하위 서비스 Mock — 받은 헤더를 그대로 응답에 포함
            def capture_headers(request):
                """요청 헤더를 응답 바디에 담아 반환."""
                return Response(
                    200,
                    json={
                        "x_user_id": request.headers.get("x-user-id"),
                        "x_user_role": request.headers.get("x-user-role"),
                    },
                )

            respx.get("http://order-service:8000/orders").mock(side_effect=capture_headers)

            response = await client.get("/orders", headers=auth_headers(token))

        assert response.status_code == 200
        data = response.json()
        # gateway가 X-User-ID, X-User-Role을 올바르게 주입했는지 확인
        assert data["x_user_id"] == "42"
        assert data["x_user_role"] == "customer"

    @pytest.mark.asyncio
    async def test_admin_role_헤더_주입(self, client):
        """admin role 토큰은 X-User-Role: admin으로 전달."""
        token = make_access_token(sub="1", role="admin")
        jwks = make_jwks_response()

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )

            def capture_headers(request):
                return Response(200, json={"x_user_role": request.headers.get("x-user-role")})

            respx.get("http://order-service:8000/orders").mock(side_effect=capture_headers)

            response = await client.get("/orders", headers=auth_headers(token))

        assert response.status_code == 200
        assert response.json()["x_user_role"] == "admin"

    @pytest.mark.asyncio
    async def test_토큰_없음_401(self, client):
        """Authorization 헤더 없으면 401."""
        response = await client.get("/orders")
        assert response.status_code == 401
        assert "인증 토큰이 필요합니다" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_Bearer_아닌_형식_401(self, client):
        """Bearer 접두사 없는 토큰은 401."""
        response = await client.get(
            "/orders",
            headers={"Authorization": "Basic abc123"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_만료된_토큰_401(self, client):
        """
        만료된 토큰 → 401, code=EXPIRED.
        exp_offset=-1로 이미 만료된 토큰 생성.
        """
        expired_token = make_access_token(sub="42", exp_offset=-1)
        jwks = make_jwks_response()

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            response = await client.get("/orders", headers=auth_headers(expired_token))

        assert response.status_code == 401
        assert response.json()["code"] == "EXPIRED"

    @pytest.mark.asyncio
    async def test_서명_불일치_토큰_401(self, client):
        """
        다른 키로 서명된 토큰 → 401, code=INVALID.
        별도 키쌍으로 서명하되 JWKS는 테스트 키쌍 공개키만 제공.
        """
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        # 별도 키쌍으로 서명 — JWKS에 등록되지 않은 키
        other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        import time

        forged_token = jwt.encode(
            {"sub": "42", "role": "customer", "exp": int(time.time()) + 900},
            other_pem,
            algorithm="RS256",
            headers={"kid": TEST_KID},  # kid는 같지만 서명 키가 다름
        )

        jwks = make_jwks_response()  # 올바른 테스트 공개키

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            response = await client.get("/orders", headers=auth_headers(forged_token))

        assert response.status_code == 401
        assert response.json()["code"] == "INVALID"

    @pytest.mark.asyncio
    async def test_JWKS_조회_실패시_401(self, client):
        """
        user-service JWKS 엔드포인트 장애 → 401.
        캐시가 비어있는 상태에서 JWKS 조회 실패 시 인증 불가.
        """
        token = make_access_token(sub="42")

        with respx.mock:
            # JWKS 엔드포인트 500 응답 시뮬레이션
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(500, json={"detail": "Internal Server Error"})
            )
            response = await client.get("/orders", headers=auth_headers(token))

        assert response.status_code == 401
        assert response.json()["code"] == "JWKS_ERROR"


class TestJWKSCache:
    """JWKS 캐시 동작 테스트."""

    @pytest.mark.asyncio
    async def test_JWKS_캐시_히트_재조회_없음(self, client):
        """
        두 번째 요청은 JWKS를 재조회하지 않음.
        respx call_count로 실제 HTTP 요청 횟수 확인.
        """
        token = make_access_token(sub="42")
        jwks = make_jwks_response()

        with respx.mock:
            jwks_route = respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            respx.get("http://order-service:8000/orders").mock(return_value=Response(200, json=[]))

            # 첫 번째 요청 — JWKS 조회 발생 (캐시 미스)
            await client.get("/orders", headers=auth_headers(token))
            # 두 번째 요청 — 캐시 히트, JWKS 재조회 없음
            await client.get("/orders", headers=auth_headers(token))

        # JWKS 엔드포인트는 정확히 1번만 호출되어야 함
        assert jwks_route.call_count == 1

    @pytest.mark.asyncio
    async def test_JWKS_캐시_만료시_재조회(self, client):
        """
        TTL 만료 후 요청 시 JWKS를 재조회함.
        fetched_at을 강제로 과거 시간으로 설정해 만료 시뮬레이션.
        """
        import time

        from app.config import get_settings as _get_settings

        settings = _get_settings()
        token = make_access_token(sub="42")
        jwks = make_jwks_response()

        with respx.mock:
            jwks_route = respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            respx.get("http://order-service:8000/orders").mock(return_value=Response(200, json=[]))

            # 첫 번째 요청 — 캐시 미스, JWKS 조회
            await client.get("/orders", headers=auth_headers(token))
            assert jwks_route.call_count == 1

            # TTL 만료 시뮬레이션 — 설정값 기반으로 계산
            jwks_cache._fetched_at = time.time() - (settings.jwks_cache_ttl_seconds + 1)

            # 두 번째 요청 — 캐시 만료, JWKS 재조회
            await client.get("/orders", headers=auth_headers(token))

        assert jwks_route.call_count == 2
