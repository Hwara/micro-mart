from fastapi import APIRouter, Depends, Header, Query, status

from ..config import get_settings
from ..database import DBSession
from ..dependencies import require_admin, verify_internal_service
from ..schemas import (
    ErrorResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    StockDeductRequest,
    StockDeductResponse,
    StockRestoreRequest,
    StockRestoreResponse,
)
from ..services.product_service import (
    create_product_service,
    deduct_stock_service,
    delete_product_service,
    get_product_service,
    list_products_service,
    restore_stock_service,
    update_product_service,
)

router = APIRouter(prefix="/products", tags=["products"])
settings = get_settings()


@router.get("", response_model=ProductListResponse)
async def list_products(
    db: DBSession,
    x_user_role: str = Header(default="customer"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    active_only: bool = Query(default=True, description="활성 상품만 조회, 관리자만 False 가능"),
) -> ProductListResponse:
    """상품 목록 조회 (offset 페이지네이션)."""
    return await list_products_service(
        db=db,
        x_user_role=x_user_role,
        page=page,
        page_size=page_size,
        active_only=active_only,
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: DBSession) -> ProductResponse:
    """상품 상세 조회."""
    return await get_product_service(product_id=product_id, db=db)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: DBSession,
    _: None = Depends(require_admin),
) -> ProductResponse:
    """상품 등록 (admin 전용)."""
    return await create_product_service(payload=payload, db=db)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: DBSession,
    _: None = Depends(require_admin),
) -> ProductResponse:
    """상품 수정 (admin 전용)."""
    return await update_product_service(product_id=product_id, payload=payload, db=db)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: DBSession,
    _: None = Depends(require_admin),
) -> None:
    """상품 소프트 삭제 (admin 전용)."""
    await delete_product_service(product_id=product_id, db=db)


@router.post(
    "/{product_id}/deduct-stock",
    response_model=StockDeductResponse,
    responses={
        409: {"model": ErrorResponse, "description": "낙관적 잠금 충돌 또는 재고 부족"},
        404: {"model": ErrorResponse},
    },
)
async def deduct_stock(
    product_id: int,
    payload: StockDeductRequest,
    db: DBSession,
    _: None = Depends(verify_internal_service),
) -> StockDeductResponse:
    """재고 차감 (order-service 전용 내부 API)."""
    return await deduct_stock_service(product_id=product_id, payload=payload, db=db)


@router.post(
    "/{product_id}/restore-stock",
    response_model=StockRestoreResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def restore_stock(
    product_id: int,
    payload: StockRestoreRequest,
    db: DBSession,
    _: None = Depends(verify_internal_service),
) -> StockRestoreResponse:
    """재고 복구 (order-service 보상 트랜잭션 전용 내부 API)."""
    return await restore_stock_service(product_id=product_id, payload=payload, db=db)
