"""
라우팅 및 리버스 프록시 테스트

검증 항목:
  - 경로 prefix에 따라 올바른 하위 서비스로 라우팅
  - 쿼리 파라미터, 요청 바디가 하위 서비스에 그대로 전달됨
  - 알 수 없는 경로 → 404
  - 하위 서비스 에러 응답이 클라이언트에 그대로 전달됨 (에러 마스킹 없음)
"""

import gzip

import pytest
import respx
from httpx import Response

from tests.conftest import auth_headers, make_access_token, make_jwks_response


@pytest.fixture
def authenticated_client_setup():
    """JWKS Mock + 유효한 토큰을 반환하는 헬퍼 픽스처."""
    token = make_access_token(sub="10", role="customer")
    jwks = make_jwks_response()
    return token, jwks


class TestRouting:
    """경로별 라우팅 검증."""

    @pytest.mark.asyncio
    async def test_orders_경로_order_service로_라우팅(self, client, authenticated_client_setup):
        """/orders/* → order-service로 프록시."""
        token, jwks = authenticated_client_setup

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            order_route = respx.get("http://order-service:8000/orders").mock(
                return_value=Response(200, json={"orders": []})
            )

            response = await client.get("/orders", headers=auth_headers(token))

        assert response.status_code == 200
        assert order_route.called  # order-service가 실제로 호출됐는지 확인

    @pytest.mark.asyncio
    async def test_products_경로_product_service로_라우팅(self, client, authenticated_client_setup):
        """/products/* → product-service로 프록시."""
        token, jwks = authenticated_client_setup

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            product_route = respx.get("http://product-service:8000/products/1").mock(
                return_value=Response(200, json={"id": 1, "name": "테스트 상품"})
            )

            response = await client.get("/products/1", headers=auth_headers(token))

        assert response.status_code == 200
        assert product_route.called

    @pytest.mark.asyncio
    async def test_auth_경로_user_service로_라우팅(self, client):
        """/auth/* → user-service로 프록시 (인증 불필요 경로)."""
        with respx.mock:
            auth_route = respx.post("http://user-service:8000/auth/login").mock(
                return_value=Response(200, json={"access_token": "new-token"})
            )

            response = await client.post(
                "/auth/login",
                json={"email": "test@test.com", "password": "pass123"},
            )

        assert response.status_code == 200
        assert auth_route.called

    @pytest.mark.asyncio
    async def test_알수없는_경로_404(self, client, authenticated_client_setup):
        """매핑되지 않은 경로 → 404."""
        token, jwks = authenticated_client_setup

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            response = await client.get("/unknown-service/test", headers=auth_headers(token))

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_쿼리파라미터_하위서비스_전달(self, client):
        """쿼리 파라미터가 하위 서비스에 그대로 전달됨."""
        with respx.mock:

            def capture_query(request):
                # 수신된 URL에 쿼리 파라미터가 포함됐는지 확인
                return Response(200, json={"query": str(request.url)})

            respx.get(url__regex=r"http://product-service:8000/products.*").mock(
                side_effect=capture_query
            )

            response = await client.get("/products?page=2&page_size=10")

        assert response.status_code == 200
        assert "page=2" in response.json()["query"]
        assert "page_size=10" in response.json()["query"]

    @pytest.mark.asyncio
    async def test_요청_바디_하위서비스_전달(self, client, authenticated_client_setup):
        """POST 요청 바디가 변형 없이 하위 서비스로 전달됨."""
        token, jwks = authenticated_client_setup
        request_body = {"items": [{"product_id": 1, "quantity": 2}]}

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )

            def capture_body(request):
                import json

                received = json.loads(request.content)
                return Response(201, json={"received": received})

            respx.post("http://order-service:8000/orders").mock(side_effect=capture_body)

            response = await client.post(
                "/orders",
                json=request_body,
                headers=auth_headers(token),
            )

        assert response.status_code == 201
        assert response.json()["received"] == request_body

    @pytest.mark.asyncio
    async def test_하위서비스_에러_그대로_전달(self, client, authenticated_client_setup):
        """
        하위 서비스 4xx/5xx 응답을 gateway가 마스킹하지 않고 그대로 전달.
        클라이언트는 하위 서비스의 에러 코드와 메시지를 그대로 받아야 함.
        """
        token, jwks = authenticated_client_setup

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            # order-service가 409 재고 부족 반환
            respx.post("http://order-service:8000/orders").mock(
                return_value=Response(
                    409,
                    json={"detail": {"detail": "재고 부족", "code": "INSUFFICIENT_STOCK"}},
                )
            )

            response = await client.post(
                "/orders",
                json={"items": [{"product_id": 1, "quantity": 999}]},
                headers=auth_headers(token),
            )

        # gateway는 409를 그대로 반환해야 함 (임의로 500으로 변환하면 안 됨)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INSUFFICIENT_STOCK"

    @pytest.mark.asyncio
    async def test_content_encoding_header_is_not_forwarded_after_decoding(
        self, client, authenticated_client_setup
    ):
        """Gateway should not forward Content-Encoding for a decoded response body."""
        token, jwks = authenticated_client_setup

        with respx.mock:
            respx.get("http://user-service:8000/auth/jwks").mock(
                return_value=Response(200, json=jwks)
            )
            respx.get("http://order-service:8000/orders").mock(
                return_value=Response(
                    200,
                    content=gzip.compress(b'{"orders":[]}'),
                    headers={"Content-Encoding": "gzip"},
                )
            )

            response = await client.get("/orders", headers=auth_headers(token))

        assert response.status_code == 200
        assert "content-encoding" not in response.headers
