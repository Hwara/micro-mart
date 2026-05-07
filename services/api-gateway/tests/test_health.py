"""
헬스체크 엔드포인트 테스트

/health는 PUBLIC_PATHS에 포함되므로 JWT 없이 접근 가능.
응답에 jwks_cached_keys 필드가 포함되는지 확인.
"""

import pytest


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_헬스체크_인증없이_200(self, client):
        """/health는 토큰 없이 200 반환."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_헬스체크_응답_형식(self, client):
        """응답 바디에 필수 필드 포함."""
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "api-gateway"
        assert "jwks_cached_keys" in data  # 캐시 상태 노출

    @pytest.mark.asyncio
    async def test_헬스체크_초기_캐시_0(self, client):
        """서비스 시작 직후 JWKS 캐시는 0 (테스트 환경에서 워밍업 미수행)."""
        response = await client.get("/health")
        # conftest.setup_env에서 캐시를 초기화했으므로 0이어야 함
        assert response.json()["jwks_cached_keys"] == 0
