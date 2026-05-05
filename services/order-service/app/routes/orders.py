"""
order-service HTTP 라우터

외부 공개 API (gateway → order-service):
  POST   /orders         주문 생성 (Saga 오케스트레이션)
  GET    /orders         내 주문 목록 조회
  GET    /orders/{id}    주문 상세 조회

라우터는 얇게 유지 — 비즈니스 로직은 services/order_service.py에 위임.
user_id는 항상 X-User-ID 헤더에서 추출 (바디 수신 금지).
"""

import structlog
from fastapi import APIRouter, Depends, Query, status

from ..database import DBSession
from ..dependencies import get_current_user_id
from ..schemas import OrderCreateRequest, OrderListResponse, OrderResponse
from ..services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])
log = structlog.get_logger(__name__)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        402: {"description": "결제 거절"},
        409: {"description": "재고 부족 또는 낙관적 락 충돌"},
        422: {"description": "비활성 상품"},
        503: {"description": "하위 서비스 불가"},
    },
    summary="주문 생성",
    description="상품 목록을 받아 재고 차감 → 결제 요청 Saga를 실행합니다.",
)
async def create_order(
    payload: OrderCreateRequest,
    db: DBSession,
    user_id: int = Depends(get_current_user_id),
) -> OrderResponse:
    """
    주문 생성 엔드포인트.

    흐름: 상품 조회 → Order 저장 → 재고 차감 → 결제 요청 → 완료
    실패 시 saga_status로 복구 가능 상태를 DB에 기록.
    """
    log.info("주문 생성 요청", user_id=user_id, item_count=len(payload.items))
    return await order_service.create_order(db=db, user_id=user_id, payload=payload)


@router.get(
    "",
    response_model=list[OrderListResponse],
    summary="내 주문 목록 조회",
)
async def list_orders(
    db: DBSession,
    user_id: int = Depends(get_current_user_id),
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    page_size: int = Query(default=20, ge=1, le=100, description="페이지당 항목 수"),
) -> list[OrderListResponse]:
    """
    로그인 사용자의 주문 목록 반환.
    최신 주문 먼저 정렬, items는 포함하지 않음 (목록 요약 응답).
    """
    return await order_service.list_orders(db=db, user_id=user_id, page=page, page_size=page_size)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    responses={
        403: {"description": "타인 주문 접근 시도"},
        404: {"description": "주문 없음"},
    },
    summary="주문 상세 조회",
)
async def get_order(
    order_id: int,
    db: DBSession,
    user_id: int = Depends(get_current_user_id),
) -> OrderResponse:
    """
    주문 상세 조회 — items(order_items) eager load 포함.
    본인 주문만 조회 가능 (IDOR 방어: user_id 검증).
    """
    return await order_service.get_order(db=db, order_id=order_id, user_id=user_id)
