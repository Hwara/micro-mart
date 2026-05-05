"""
order-service 비즈니스 로직 — Saga 오케스트레이션

주문 생성 흐름:
  ① 상품 정보 조회 (가격·활성화 여부 확인)
  ② Order + OrderItems DB 저장 (PENDING / STARTED)
  ③ 재고 차감 (순차 처리)
  ④ saga_status=STOCK_DEDUCTED, stock_deducted=True 커밋
  ⑤ 결제 요청
  ⑥ 완료 또는 보상 트랜잭션

보상 트랜잭션 원칙:
  - saga_status=STOCK_ROLLBACK_NEEDED를 먼저 커밋 (장애 복구 근거)
  - 재고 복구 실패 시 FAILED로 처리하되 로그 남김 (배치 복구 대상)
"""

import json

import structlog
from fastapi import HTTPException, status
from opentelemetry import metrics
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Order, OrderItem, OrderStatus, SagaStatus
from ..nats_client import get_nats_client
from ..schemas import OrderCreateRequest, OrderListResponse, OrderResponse
from . import http_clients
from .http_clients import PaymentServiceError, ProductServiceError

log = structlog.get_logger(__name__)

# ─── 관찰성 메트릭 ────────────────────────────────────────────────
meter = metrics.get_meter("order-service")

order_created_counter = meter.create_counter(
    "order_created_total",
    description="주문 생성 요청 총 횟수",
)
order_completed_counter = meter.create_counter(
    "order_completed_total",
    description="주문 완료 횟수",
)
order_failed_counter = meter.create_counter(
    "order_failed_total",
    description="주문 실패 횟수 (reason 레이블)",
)
order_amount_histogram = meter.create_histogram(
    "order_amount_krw",
    description="주문 금액 분포 (원단위)",
    unit="KRW",
)
saga_rollback_counter = meter.create_counter(
    "saga_stock_rollback_total",
    description="재고 롤백 보상 트랜잭션 횟수",
)


async def create_order(
    db: AsyncSession,
    user_id: int,
    payload: OrderCreateRequest,
) -> OrderResponse:
    """
    주문 생성 Saga 오케스트레이터.

    실패 경로:
    - 상품 조회 실패/비활성: 즉시 HTTPException (Order 저장 전)
    - 재고 차감 실패: Order FAILED 저장 후 HTTPException
    - 결제 실패: 재고 롤백 후 Order FAILED 저장, HTTPException
    """

    order_created_counter.add(1)

    # ── ① 상품 정보 일괄 조회 ────────────────────────────────────
    # 주문 전 모든 상품을 미리 조회해 가격·활성화 상태 확인.
    # 재고는 deduct-stock API에서 원자적으로 검사하므로 여기선 확인만.
    products: dict[int, dict] = {}
    for item_req in payload.items:
        try:
            product = await http_clients.get_product(item_req.product_id)
        except ProductServiceError as e:
            log.warning(
                "상품 조회 실패로 주문 거부",
                product_id=item_req.product_id,
                code=e.code,
                user_id=user_id,
            )
            order_failed_counter.add(1, {"reason": e.code})
            raise HTTPException(
                status_code=e.status_code,
                detail={"detail": str(e), "code": e.code},
            ) from e

        if not product.get("is_active", False):
            order_failed_counter.add(1, {"reason": "PRODUCT_INACTIVE"})
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "detail": f"비활성화된 상품입니다. (product_id={item_req.product_id})",
                    "code": "PRODUCT_INACTIVE",
                },
            )
        products[item_req.product_id] = product

    # ── ② Order + OrderItems 생성 (PENDING / STARTED) ────────────
    # 총액은 상품 조회 시점 가격으로 계산 — 이후 가격 변경 무관
    total_amount = sum(products[item.product_id]["price"] * item.quantity for item in payload.items)
    order_amount_histogram.record(total_amount)

    order = Order(
        user_id=user_id,
        status=OrderStatus.PENDING,
        total_amount=total_amount,
        saga_status=SagaStatus.STARTED,
        stock_deducted=False,
    )
    db.add(order)
    await db.flush()  # order.id 채번

    order_items = []
    for item_req in payload.items:
        product = products[item_req.product_id]
        unit_price = product["price"]
        subtotal = unit_price * item_req.quantity
        oi = OrderItem(
            order_id=order.id,
            product_id=item_req.product_id,
            product_name=product["name"],
            unit_price=unit_price,
            quantity=item_req.quantity,
            discount_amount=0,
            subtotal=subtotal,
        )
        db.add(oi)
        order_items.append(oi)

    await db.commit()
    await db.refresh(order)

    log.info(
        "주문 생성 완료 (PENDING)",
        order_id=order.id,
        user_id=user_id,
        total_amount=total_amount,
        item_count=len(order_items),
    )

    # ── ③ 재고 차감 (순차) ──────────────────────────────────────
    # 복수 상품 재고 차감은 순차 처리.
    # 병렬 처리(asyncio.gather)도 가능하지만, 부분 성공 시 롤백 대상 추적이 복잡해짐.
    # 단순성 우선: 순차 차감, 실패 시 지금까지 성공한 항목만 롤백.
    deducted_items: list[tuple[int, int]] = []  # (product_id, quantity) 롤백용

    for item_req in payload.items:
        current_version = products[item_req.product_id]["version"]
        try:
            await http_clients.deduct_stock(
                product_id=item_req.product_id,
                quantity=item_req.quantity,
                expected_version=current_version,
            )
            deducted_items.append((item_req.product_id, item_req.quantity))
        except ProductServiceError as e:
            log.warning(
                "재고 차감 실패 — 주문 실패 처리",
                order_id=order.id,
                product_id=item_req.product_id,
                code=e.code,
            )
            # 지금까지 차감된 재고 롤백
            for pid, qty in deducted_items:
                ok = await http_clients.restore_stock(pid, qty)
                if not ok:
                    rollback_success = False

            order.status = OrderStatus.FAILED
            order.saga_status = (
                SagaStatus.STOCK_ROLLED_BACK if rollback_success else SagaStatus.FAILED
            )
            order.failure_reason = e.code
            await db.commit()

            order_failed_counter.add(1, {"reason": e.code})
            raise HTTPException(
                status_code=e.status_code,
                detail={"detail": str(e), "code": e.code},
            ) from e

    # ── ④ STOCK_DEDUCTED 상태 커밋 ──────────────────────────────
    # stock_deducted=True 커밋 이후부터 결제 실패 시 보상 트랜잭션 필수
    order.status = OrderStatus.STOCK_DEDUCTED
    order.saga_status = SagaStatus.STOCK_DEDUCTED
    order.stock_deducted = True
    await db.commit()

    log.info("재고 차감 완료", order_id=order.id, deducted_items=deducted_items)

    # ── ⑤ 결제 요청 ─────────────────────────────────────────────
    order.status = OrderStatus.PAYMENT_REQUESTED
    order.saga_status = SagaStatus.PAYMENT_REQUESTED
    await db.commit()

    payment_result: dict | None = None
    try:
        payment_result = await http_clients.request_payment(
            order_id=order.id,
            user_id=user_id,
            amount=total_amount,
        )
    except PaymentServiceError as e:
        # ── 결제 실패 → 보상 트랜잭션 ──────────────────────────
        # ⚠️ STOCK_ROLLBACK_NEEDED 먼저 커밋: 서버 크래시 시에도 복구 배치가 스캔 가능
        order.saga_status = SagaStatus.STOCK_ROLLBACK_NEEDED
        order.failure_reason = e.code
        await db.commit()

        log.warning(
            "결제 실패 — 재고 롤백 시작",
            order_id=order.id,
            failure_reason=e.code,
        )
        saga_rollback_counter.add(1)

        # 재고 복구 (best-effort)
        rollback_success = True
        for pid, qty in deducted_items:
            ok = await http_clients.restore_stock(pid, qty)
            # restore_stock은 내부에서 예외를 흡수하므로 여기선 성공 여부 추적만
            if not ok:
                rollback_success = False

        order.status = OrderStatus.FAILED
        order.saga_status = SagaStatus.STOCK_ROLLED_BACK if rollback_success else SagaStatus.FAILED
        await db.commit()

        _payment_status_map = {
            402: status.HTTP_402_PAYMENT_REQUIRED,  # 정상 결제 거절
            504: status.HTTP_504_GATEWAY_TIMEOUT,  # 타임아웃
            503: status.HTTP_503_SERVICE_UNAVAILABLE,  # 서비스 불가
        }
        http_status = _payment_status_map.get(e.status_code, status.HTTP_502_BAD_GATEWAY)

        order_failed_counter.add(1, {"reason": e.code})
        raise HTTPException(
            status_code=http_status,
            detail={"detail": str(e), "code": e.code},
        ) from e

    # ── ⑥ 주문 완료 ─────────────────────────────────────────────
    order.status = OrderStatus.COMPLETED
    order.saga_status = SagaStatus.COMPLETED
    order.payment_id = payment_result["id"]
    await db.commit()
    await db.refresh(order)

    # NATS 이벤트 발행 (notification-service 소비)
    await _publish_order_completed(order)

    order_completed_counter.add(1)
    log.info(
        "주문 완료",
        order_id=order.id,
        user_id=user_id,
        payment_id=order.payment_id,
        total_amount=total_amount,
    )

    # ── 최종 응답 — items eager load ─────────────────────────────────
    # db.refresh(order)는 order 스칼라 컬럼만 갱신, relationship(items)은 로드하지 않음.
    # model_validate() 내부에서 order.items에 접근하면 lazy load가 트리거되는데,
    # 동기 컨텍스트에서는 await이 불가 → MissingGreenlet 에러 발생.
    # selectinload로 items를 await 가능한 컨텍스트에서 미리 로드해 해결.

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))  # ← items를 지금 여기서 로드
        .where(Order.id == order.id)
    )
    order = result.scalar_one()

    return OrderResponse.model_validate(order)


async def _publish_order_completed(order: Order) -> None:
    """
    NATS order.completed 이벤트 발행.

    nats_client 싱글턴에서 커넥션 조회 → 커넥션 재사용 (오버헤드 없음).
    실패해도 주문은 COMPLETED 유지 (best-effort).
    향후 outbox 패턴으로 교체하면 at-least-once 보장 가능.
    """

    try:
        nc = get_nats_client()
        if nc is None or nc.is_closed:
            log.warning("NATS 클라이언트 없음 — 이벤트 발행 건너뜀", order_id=order.id)
            return

        payload = {
            "order_id": order.id,
            "user_id": order.user_id,
            "total_amount": order.total_amount,
            "payment_id": order.payment_id,
        }
        await nc.publish("order.completed", json.dumps(payload).encode())
        log.info("order.completed 이벤트 발행 완료", order_id=order.id)

    except Exception as e:
        log.error(
            "order.completed 이벤트 발행 실패",
            order_id=order.id,
            error=str(e),
        )


async def get_order(db: AsyncSession, order_id: int, user_id: int) -> OrderResponse:
    """
    주문 상세 조회.

    본인 주문만 조회 가능 — user_id 검증 (외부에서 넘어온 order_id만으로 조회 금지).
    """

    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "주문을 찾을 수 없습니다.", "code": "ORDER_NOT_FOUND"},
        )

    # 본인 주문만 조회 허용 (타인 주문 접근 차단)
    if order.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "접근 권한이 없습니다.", "code": "FORBIDDEN"},
        )

    return OrderResponse.model_validate(order)


async def list_orders(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> list:
    """
    내 주문 목록 조회 (페이지네이션).

    최신 주문 먼저 정렬. items는 포함하지 않음 (목록용 요약 응답).
    """

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(desc(Order.created_at))
        .offset(offset)
        .limit(page_size)
    )
    orders = result.scalars().all()
    return [OrderListResponse.model_validate(o) for o in orders]
