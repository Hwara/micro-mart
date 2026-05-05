"""
order-service 라우터 레이어 테스트

테스트 대상: routes/orders.py (HTTP 계층)
- 인증 헤더(X-User-ID) 누락/잘못된 형식 검증
- 요청 바디 유효성 검증 (Pydantic)
- 헬스체크

비즈니스 로직은 test_order_service.py에서 담당하므로
여기서는 HTTP 계층 관심사에만 집중.
"""

from unittest.mock import AsyncMock

import pytest

from .conftest import TEST_USER_ID, make_payment_result, make_product, user_headers


class TestOrdersAPIAuth:
    """인증 헤더 검증 테스트."""

    @pytest.mark.asyncio
    async def test_X_User_ID_누락_401(self, client):
        """X-User-ID 헤더 없으면 401."""
        response = await client.post(
            "/orders",
            json={"items": [{"product_id": 1, "quantity": 1}]},
            # 헤더 없음 — gateway 우회 시뮬레이션
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_X_User_ID_빈값_401(self, client):
        """X-User-ID 빈 문자열 → 401."""
        response = await client.post(
            "/orders",
            json={"items": [{"product_id": 1, "quantity": 1}]},
            headers={"X-User-ID": ""},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_X_User_ID_문자열_400(self, client):
        """X-User-ID가 숫자가 아닌 문자열 → 400."""
        response = await client.post(
            "/orders",
            json={"items": [{"product_id": 1, "quantity": 1}]},
            headers={"X-User-ID": "not-a-number"},
        )
        assert response.status_code == 400


class TestOrdersAPIValidation:
    """요청 바디 유효성 검증 테스트."""

    @pytest.mark.asyncio
    async def test_items_빈배열_422(self, client):
        """items가 빈 배열이면 422."""
        response = await client.post(
            "/orders",
            json={"items": []},
            headers=user_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_quantity_0이하_422(self, client):
        """quantity가 0 이하면 422."""
        response = await client.post(
            "/orders",
            json={"items": [{"product_id": 1, "quantity": 0}]},
            headers=user_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_product_id_없음_422(self, client):
        """product_id 누락 시 422."""
        response = await client.post(
            "/orders",
            json={"items": [{"quantity": 1}]},
            headers=user_headers(),
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_중복_product_id_422(self, client):
        """동일 product_id가 두 번 포함되면 422."""
        response = await client.post(
            "/orders",
            json={
                "items": [
                    {"product_id": 1, "quantity": 2},
                    {"product_id": 1, "quantity": 3},
                ]
            },
            headers=user_headers(),
        )
        assert response.status_code == 422


class TestOrdersAPISuccess:
    """주문 생성 정상 흐름 API 레벨 검증."""

    @pytest.mark.asyncio
    async def test_주문생성_201_응답구조(self, client, mocker):
        """주문 생성 성공 시 201과 응답 구조 검증."""
        product = make_product(price=15000, version=1)
        payment = make_payment_result(order_id=1, amount=15000)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=None),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(return_value=payment),
        )
        mocker.patch(
            "app.services.order_service._publish_order_completed",
            new=AsyncMock(),
        )

        response = await client.post(
            "/orders",
            json={"items": [{"product_id": 1, "quantity": 1}]},
            headers=user_headers(),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "COMPLETED"
        assert data["total_amount"] == 15000
        assert data["user_id"] == TEST_USER_ID
        assert len(data["items"]) == 1
        assert data["items"][0]["unit_price"] == 15000
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_주문목록_조회_200(self, client, mocker):
        """GET /orders — 빈 목록도 200."""
        response = await client.get("/orders", headers=user_headers())
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_없는주문_조회_404(self, client):
        """GET /orders/{id} — 존재하지 않는 ID → 404."""
        response = await client.get("/orders/99999", headers=user_headers())
        assert response.status_code == 404


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_헬스체크_인증없이_접근(self, client):
        """헬스체크는 인증 없이 접근 가능."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "order-service"
        assert "nats_connected" in data
