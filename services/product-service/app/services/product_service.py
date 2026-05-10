import structlog
from fastapi import HTTPException, status
from opentelemetry import metrics
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import get_cached_product, invalidate_product_cache, set_cached_product
from ..config import get_settings
from ..database import redis_client
from ..models import Product
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

log = structlog.get_logger(__name__)
settings = get_settings()
meter = metrics.get_meter("product-service")

cache_hit_counter = meter.create_counter(
    "product_cache_hits_total",
    description="Redis 캐시 히트 횟수",
)
cache_miss_counter = meter.create_counter(
    "product_cache_misses_total",
    description="Redis 캐시 미스 횟수",
)
stock_deduct_counter = meter.create_counter(
    "product_stock_deduct_total",
    description="재고 차감 요청 수",
    unit="1",
)
stock_insufficient_counter = meter.create_counter(
    "product_stock_insufficient_total",
    description="재고 부족으로 인한 차감 실패 수",
)
stock_conflict_counter = meter.create_counter(
    "product_stock_conflict_total",
    description="낙관적 잠금 충돌로 인한 차감 실패 수",
)


async def list_products_service(
    db: AsyncSession,
    x_user_role: str,
    page: int,
    page_size: int,
    active_only: bool,
) -> ProductListResponse:
    """
    상품 목록을 offset 페이지네이션으로 조회한다.

    일반 고객의 비활성 상품 조회를 차단하는 권한 분기는 HTTP 헤더에서
    주입된 role을 기준으로 하되, 비즈니스 규칙 자체는 service 계층에 둔다.
    """
    offset = (page - 1) * page_size

    if not active_only and x_user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성 상품 조회는 관리자만 가능합니다.",
        )

    conditions = []
    if active_only:
        conditions.append(Product.is_active.is_(True))

    total_stmt = select(func.count()).select_from(Product)
    items_stmt = (
        select(Product)
        .where(*conditions)
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    if conditions:
        total_stmt = total_stmt.where(*conditions)

    total_result = await db.execute(total_stmt)
    total = total_result.scalar_one()

    items_result = await db.execute(items_stmt)
    products = items_result.scalars().all()

    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in products],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


async def get_product_service(product_id: int, db: AsyncSession) -> ProductResponse:
    """
    상품 상세를 Cache-Aside 패턴으로 조회한다.

    캐시 히트 시 DB를 조회하지 않는 기존 성능 특성을 유지한다.
    """
    cached = await get_cached_product(redis_client, product_id)
    if cached:
        cache_hit_counter.add(1, {"result": "hit"})
        log.debug("상품 캐시 히트", product_id=product_id)
        return ProductResponse(**cached)

    cache_miss_counter.add(1, {"result": "miss"})
    log.debug("상품 캐시 미스", product_id=product_id)

    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품을 찾을 수 없습니다.",
        )

    response = ProductResponse.model_validate(product)
    await set_cached_product(
        redis_client,
        product_id,
        response.model_dump(mode="json"),
        settings.product_cache_ttl,
    )

    return response


async def create_product_service(payload: ProductCreate, db: AsyncSession) -> ProductResponse:
    """관리자 상품 등록을 처리하고 생성된 상품 응답을 반환한다."""
    product = Product(**payload.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)

    log.info("상품 생성 성공", product_id=product.id, name=product.name)
    return ProductResponse.model_validate(product)


async def update_product_service(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession,
) -> ProductResponse:
    """
    상품 정보를 수정하고 상세/목록 캐시를 무효화한다.

    수정 후 캐시를 갱신하지 않고 삭제해 다음 조회 시 DB 최신값으로 자연스럽게
    다시 채운다. 불필요한 캐시 쓰기를 줄이는 기존 판단을 유지한다.
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품을 찾을 수 없습니다.",
        )

    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)

    await invalidate_product_cache(redis_client, product_id)
    log.info("상품 수정 성공", product_id=product_id)

    return ProductResponse.model_validate(product)


async def delete_product_service(product_id: int, db: AsyncSession) -> None:
    """
    상품을 물리 삭제하지 않고 is_active=False로 소프트 삭제한다.

    주문 이력의 논리적 product_id 참조를 보존하기 위해 기존 동작을 유지한다.
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품을 찾을 수 없습니다.",
        )

    product.is_active = False
    await db.commit()

    await invalidate_product_cache(redis_client, product_id)
    log.info("상품 삭제 성공", product_id=product_id)


async def deduct_stock_service(
    product_id: int,
    payload: StockDeductRequest,
    db: AsyncSession,
) -> StockDeductResponse:
    """
    단일 UPDATE로 낙관적 잠금과 재고 충분 조건을 원자적으로 검사한다.

    SELECT 후 UPDATE 방식은 TOCTOU 경쟁 조건이 있으므로 기존 단일 UPDATE
    경계를 유지한다.
    """
    stock_deduct_counter.add(1, {"result": "deduct"})

    stmt = (
        update(Product)
        .where(
            Product.id == product_id,
            Product.is_active.is_(True),
            Product.version == payload.expected_version,
            Product.stock >= payload.quantity,
        )
        .values(
            stock=Product.stock - payload.quantity,
            version=Product.version + 1,
        )
        .returning(Product.stock, Product.version)
    )

    result = await db.execute(stmt)
    row = result.fetchone()

    if row is None:
        check = await db.execute(
            select(Product.stock, Product.version, Product.is_active).where(
                Product.id == product_id
            )
        )
        product_state = check.fetchone()

        if not product_state or not product_state.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="상품을 찾을 수 없습니다.",
            )

        if product_state.version != payload.expected_version:
            stock_conflict_counter.add(1, {"result": "conflict"})
            log.warning(
                "상품 재고 감소 동시 요청으로 인한 충돌",
                product_id=product_id,
                expected_version=payload.expected_version,
                actual_version=product_state.version,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse(
                    detail="동시 요청으로 인한 충돌입니다. 재시도해 주세요.",
                    code="VERSION_CONFLICT",
                ).model_dump(),
            )

        stock_insufficient_counter.add(1, {"result": "insufficient"})
        log.warning(
            "상품 재고 부족",
            product_id=product_id,
            requested=payload.quantity,
            available=product_state.stock,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                detail=f"재고가 부족합니다. 현재 재고: {product_state.stock}",
                code="INSUFFICIENT_STOCK",
            ).model_dump(),
        )

    await db.commit()
    await invalidate_product_cache(redis_client, product_id)

    log.info(
        "상품 재고 차감 성공",
        product_id=product_id,
        quantity=payload.quantity,
        remaining_stock=row.stock,
        new_version=row.version,
    )

    return StockDeductResponse(
        product_id=product_id,
        remaining_stock=row.stock,
        new_version=row.version,
    )


async def restore_stock_service(
    product_id: int,
    payload: StockRestoreRequest,
    db: AsyncSession,
) -> StockRestoreResponse:
    """
    보상 트랜잭션용 재고 복구를 처리한다.

    복구는 이미 차감된 수량을 되돌리는 단방향 증가 연산이므로, version
    충돌로 복구가 막히지 않도록 낙관적 잠금을 적용하지 않는다.
    """
    stmt = (
        update(Product)
        .where(
            Product.id == product_id,
            Product.is_active.is_(True),
        )
        .values(
            stock=Product.stock + payload.quantity,
            version=Product.version + 1,
        )
        .returning(Product.stock, Product.version)
    )

    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="상품을 찾을 수 없습니다.",
        )

    await invalidate_product_cache(redis_client, product_id)

    log.info(
        "재고 복구 완료 (보상 트랜잭션)",
        product_id=product_id,
        quantity=payload.quantity,
        remaining_stock=row.stock,
        new_version=row.version,
    )

    return StockRestoreResponse(
        product_id=product_id,
        remaining_stock=row.stock,
        new_version=row.version,
    )
