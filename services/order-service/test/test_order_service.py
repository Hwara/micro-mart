"""
order-service Saga 로직 단위 테스트

테스트 대상: services/order_service.py (비즈니스 로직)
모킹 대상:  services/http_clients.py (외부 서비스 HTTP 호출)

외부 HTTP 호출을 mock하는 이유:
- product/payment-service 기동 없이 Saga 분기 경로를 독립적으로 검증
- 재고 부족, 결제 거절, VERSION_CONFLICT 등 재현하기 어려운 경계 조건 테스트 가능
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from app.models import Order, OrderStatus, SagaStatus
from app.schemas import OrderCreateRequest, OrderItemRequest
from app.services import order_service
from app.services.http_clients import PaymentServiceError, ProductServiceError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .conftest import (
    TEST_USER_ID,
    make_payment_result,
    make_product,
)

# ── 공통 픽스처 ────────────────────────────────────────────────


def _single_item_payload(
    product_id: int = 1,
    quantity: int = 2,
) -> OrderCreateRequest:
    """단일 상품 주문 요청 픽스처 헬퍼."""
    return OrderCreateRequest(items=[OrderItemRequest(product_id=product_id, quantity=quantity)])


def _multi_item_payload() -> OrderCreateRequest:
    """복수 상품 주문 요청 픽스처 헬퍼."""
    return OrderCreateRequest(
        items=[
            OrderItemRequest(product_id=1, quantity=2),
            OrderItemRequest(product_id=2, quantity=1),
        ]
    )


# ── 정상 흐름 ──────────────────────────────────────────────────


class TestCreateOrderSuccess:
    """정상 주문 생성 Saga 흐름."""

    @pytest.mark.asyncio
    async def test_단일상품_주문_완료(self, db_session, mocker):
        """
        정상 흐름: 상품 조회 → 재고 차감 → 결제 → COMPLETED.
        총액이 price * quantity로 정확히 계산되는지 검증.
        """
        product = make_product(product_id=1, price=10000, version=1)
        payment = make_payment_result(order_id=1, amount=20000)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),  # new_version
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(return_value=payment),
        )
        mocker.patch(
            "app.services.order_service._publish_order_completed",
            new=AsyncMock(),
        )

        result = await order_service.create_order(
            db=db_session,
            user_id=TEST_USER_ID,
            payload=_single_item_payload(product_id=1, quantity=2),
        )
        result_db = await db_session.execute(select(Order))
        order = result_db.scalar_one()

        assert result.status == OrderStatus.COMPLETED
        assert order.saga_status == SagaStatus.COMPLETED
        assert result.total_amount == 20000  # 10000 * 2
        assert result.payment_id == payment["id"]
        assert len(result.items) == 1
        assert result.items[0].unit_price == 10000
        assert result.items[0].quantity == 2

    @pytest.mark.asyncio
    async def test_복수상품_주문_완료(self, db_session, mocker):
        """복수 상품 주문 시 총액이 각 상품 price * quantity 합산으로 계산."""
        product1 = make_product(product_id=1, price=10000, version=1)
        product2 = make_product(product_id=2, price=5000, version=3)
        # 총액: 10000*2 + 5000*1 = 25000
        payment = make_payment_result(order_id=1, amount=25000)

        async def mock_get_product(product_id: int):
            return product1 if product_id == 1 else product2

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=mock_get_product,
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(return_value=payment),
        )
        mocker.patch(
            "app.services.order_service._publish_order_completed",
            new=AsyncMock(),
        )

        result = await order_service.create_order(
            db=db_session,
            user_id=TEST_USER_ID,
            payload=_multi_item_payload(),
        )

        assert result.status == OrderStatus.COMPLETED
        assert result.total_amount == 25000
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_deduct_stock에_expected_version_전달(self, db_session, mocker):
        """
        get_product에서 받은 version이 deduct_stock의 expected_version으로
        정확히 전달되는지 검증 — 낙관적 잠금 계약 확인.
        """
        product = make_product(product_id=1, price=10000, version=7)  # version=7
        payment = make_payment_result(order_id=1, amount=10000)

        mock_deduct = AsyncMock(return_value=8)
        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=mock_deduct,
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(return_value=payment),
        )
        mocker.patch(
            "app.services.order_service._publish_order_completed",
            new=AsyncMock(),
        )

        await order_service.create_order(
            db=db_session,
            user_id=TEST_USER_ID,
            payload=_single_item_payload(product_id=1, quantity=1),
        )

        # expected_version=7이 전달됐는지 확인
        mock_deduct.assert_called_once_with(
            product_id=1,
            quantity=1,
            expected_version=7,
        )


# ── 재고 차감 실패 경로 ────────────────────────────────────────


class TestCreateOrderStockFailure:
    """재고 차감 실패 시 Saga 상태 검증."""

    @pytest.mark.asyncio
    async def test_재고부족_주문실패(self, db_session, mocker):
        """
        재고 부족(INSUFFICIENT_STOCK) → Order FAILED, saga FAILED.
        restore_stock 호출 없음 (차감된 게 없으므로).
        """
        product = make_product(product_id=1, price=10000, version=1)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(
                side_effect=ProductServiceError(
                    "재고 부족", code="INSUFFICIENT_STOCK", status_code=409
                )
            ),
        )
        mock_restore = mocker.patch(
            "app.services.order_service.http_clients.restore_stock",
            new=AsyncMock(),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "INSUFFICIENT_STOCK"

        # 차감된 항목 없으므로 restore_stock 호출 없어야 함
        mock_restore.assert_not_called()

        # DB에 FAILED 상태로 저장됐는지 확인
        result = await db_session.execute(select(Order))
        order = result.scalar_one_or_none()
        assert order is not None
        assert order.status == OrderStatus.FAILED
        assert order.saga_status == SagaStatus.FAILED
        assert order.failure_reason == "INSUFFICIENT_STOCK"

    @pytest.mark.asyncio
    async def test_복수상품_첫번째성공_두번째실패_롤백(self, db_session, mocker):
        """
        복수 상품 중 첫 번째 차감 성공, 두 번째 실패 →
        첫 번째 상품의 restore_stock 호출 확인 (부분 롤백).
        """
        product1 = make_product(product_id=1, price=10000, version=1)
        product2 = make_product(product_id=2, price=5000, version=1)

        async def mock_get_product(product_id: int):
            return product1 if product_id == 1 else product2

        call_count = {"n": 0}

        async def mock_deduct(product_id, quantity, expected_version):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # 두 번째 상품 차감 실패
                raise ProductServiceError("재고 부족", code="INSUFFICIENT_STOCK", status_code=409)
            return expected_version + 1

        mock_restore = mocker.patch(
            "app.services.order_service.http_clients.restore_stock",
            new=AsyncMock(),
        )
        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=mock_get_product,
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=mock_deduct,
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_multi_item_payload(),
            )

        # product_id=1의 재고만 복구 (product_id=2는 차감 실패했으므로 복구 대상 아님)
        mock_restore.assert_called_once_with(1, 2)

    @pytest.mark.asyncio
    async def test_상품조회_실패_주문거부(self, db_session, mocker):
        """
        product-service 조회 실패 → Order 저장 전 즉시 HTTPException.
        DB에 Order 레코드가 생성되지 않아야 함.
        """
        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(
                side_effect=ProductServiceError(
                    "상품 없음", code="PRODUCT_NOT_FOUND", status_code=404
                )
            ),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(),
            )

        assert exc_info.value.status_code == 404

        # Order 레코드 없어야 함 (실패 전에 저장 안 됨)
        result = await db_session.execute(select(Order))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_비활성상품_주문거부(self, db_session, mocker):
        """비활성 상품(is_active=False) 주문 요청 → 422."""
        inactive_product = make_product(is_active=False)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=inactive_product),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(),
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PRODUCT_INACTIVE"


# ── 결제 실패 보상 트랜잭션 경로 ──────────────────────────────


class TestCreateOrderPaymentFailure:
    """결제 실패 시 보상 트랜잭션(재고 롤백) Saga 상태 검증."""

    @pytest.mark.asyncio
    async def test_결제실패_재고롤백_수행(self, db_session, mocker):
        """
        결제 거절(PAYMENT_REJECTED) →
        재고 롤백 수행 → Order FAILED, saga STOCK_ROLLED_BACK.

        핵심 검증:
        1. restore_stock이 올바른 인자로 호출됐는가
        2. saga_status가 STOCK_ROLLBACK_NEEDED → STOCK_ROLLED_BACK으로 전환됐는가
        """
        product = make_product(product_id=1, price=10000, version=1)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(
                side_effect=PaymentServiceError(
                    "결제 거절", code="PAYMENT_REJECTED", status_code=402
                )
            ),
        )
        mock_restore = mocker.patch(
            "app.services.order_service.http_clients.restore_stock",
            new=AsyncMock(),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(product_id=1, quantity=2),
            )

        assert exc_info.value.status_code == 402

        # restore_stock이 차감된 항목으로 호출됐는지
        mock_restore.assert_called_once_with(1, 2)

        # DB 상태 확인
        result = await db_session.execute(select(Order))
        order = result.scalar_one()
        assert order.status == OrderStatus.FAILED
        assert order.saga_status == SagaStatus.STOCK_ROLLED_BACK
        assert order.stock_deducted is True  # 차감은 됐었음
        assert order.failure_reason == "PAYMENT_REJECTED"

    @pytest.mark.asyncio
    async def test_결제실패_DB에_STOCK_ROLLBACK_NEEDED_먼저_커밋(self, db_session, mocker):
        """
        결제 실패 직후 saga_status=STOCK_ROLLBACK_NEEDED가
        restore_stock 호출 전에 DB에 커밋됐는지 검증.

        장애 복구 시나리오: restore_stock 중 서버 크래시 나도
        DB에 STOCK_ROLLBACK_NEEDED 상태가 남아 복구 배치가 스캔 가능해야 함.
        restore_stock 호출 직전 DB를 스냅샷해서 상태를 확인.
        """
        product = make_product(product_id=1, price=10000, version=1)
        saga_state_before_restore: list[str] = []

        async def capture_then_restore(product_id, quantity):
            # restore_stock 호출 직전 DB 상태 캡처
            result = await db_session.execute(select(Order))
            order = result.scalar_one_or_none()
            if order:
                saga_state_before_restore.append(order.saga_status.value)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(
                side_effect=PaymentServiceError(
                    "결제 거절", code="PAYMENT_REJECTED", status_code=402
                )
            ),
        )
        mocker.patch(
            "app.services.order_service.http_clients.restore_stock",
            new=capture_then_restore,
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(),
            )

        # restore_stock 호출 시점에 STOCK_ROLLBACK_NEEDED였어야 함
        assert len(saga_state_before_restore) == 1
        assert saga_state_before_restore[0] == "STOCK_ROLLBACK_NEEDED"

    @pytest.mark.asyncio
    async def test_결제서비스_타임아웃_재고롤백(self, db_session, mocker):
        """결제 타임아웃(PAYMENT_TIMEOUT)도 보상 트랜잭션 실행."""
        product = make_product(product_id=1, price=10000, version=1)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(
                side_effect=PaymentServiceError("타임아웃", code="PAYMENT_TIMEOUT", status_code=504)
            ),
        )
        mock_restore = mocker.patch(
            "app.services.order_service.http_clients.restore_stock",
            new=AsyncMock(),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await order_service.create_order(
                db=db_session,
                user_id=TEST_USER_ID,
                payload=_single_item_payload(product_id=1, quantity=3),
            )

        mock_restore.assert_called_once_with(1, 3)


# ── 주문 조회 테스트 ───────────────────────────────────────────


class TestGetOrder:
    """주문 조회 및 IDOR 방어 검증."""

    @pytest_asyncio.fixture
    async def completed_order(self, db_session, mocker) -> Order:
        """COMPLETED 상태 주문을 미리 생성하는 픽스처."""
        product = make_product(price=10000, version=1)
        payment = make_payment_result(order_id=1, amount=10000)

        mocker.patch(
            "app.services.order_service.http_clients.get_product",
            new=AsyncMock(return_value=product),
        )
        mocker.patch(
            "app.services.order_service.http_clients.deduct_stock",
            new=AsyncMock(return_value=2),
        )
        mocker.patch(
            "app.services.order_service.http_clients.request_payment",
            new=AsyncMock(return_value=payment),
        )
        mocker.patch(
            "app.services.order_service._publish_order_completed",
            new=AsyncMock(),
        )

        await order_service.create_order(
            db=db_session,
            user_id=TEST_USER_ID,
            payload=_single_item_payload(quantity=1),
        )

        result = await db_session.execute(select(Order).options(selectinload(Order.items)))
        return result.scalar_one()

    @pytest.mark.asyncio
    async def test_본인주문_조회_성공(self, db_session, completed_order):
        """본인 주문은 정상 조회."""
        result = await order_service.get_order(
            db=db_session,
            order_id=completed_order.id,
            user_id=TEST_USER_ID,
        )
        assert result.id == completed_order.id
        assert result.user_id == TEST_USER_ID

    @pytest.mark.asyncio
    async def test_타인주문_조회_403(self, db_session, completed_order):
        """
        타인의 주문 조회 시도 → 403 FORBIDDEN.
        IDOR(Insecure Direct Object Reference) 방어 검증.
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.get_order(
                db=db_session,
                order_id=completed_order.id,
                user_id=TEST_USER_ID + 1,  # 다른 user_id
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_없는주문_조회_404(self, db_session):
        """존재하지 않는 order_id → 404."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await order_service.get_order(
                db=db_session,
                order_id=99999,
                user_id=TEST_USER_ID,
            )
        assert exc_info.value.status_code == 404
