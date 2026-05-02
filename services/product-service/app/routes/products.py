import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from opentelemetry import metrics
from sqlalchemy import func, select, update

from ..cache import (
    get_cached_product,
    invalidate_product_cache,
    set_cached_product,
)
from ..config import get_settings
from ..database import DBSession, redis_client
from ..models import Product
from ..schemas import (
    ErrorResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    StockDeductRequest,
    StockDeductResponse,
)

router = APIRouter(prefix="/products", tags=["products"])
log = structlog.get_logger(__name__)
settings = get_settings()

# ─── 관찰성 메트릭 ───────────────────────────────────────────────
# 설계 문서 관찰성 포인트: 캐시 히트율, 재고 부족 이벤트
meter = metrics.get_meter("product-service")

# Cache-Aside 히트/미스 카운터 → Grafana에서 히트율 = hit / (hit + miss)
cache_hit_counter = meter.create_counter(
    "product_cache_hits_total",
    description="Redis 캐시 히트 횟수",
)
cache_miss_counter = meter.create_counter(
    "product_cache_misses_total",
    description="Redis 캐시 미스 횟수",
)

# 재고 관련 이벤트
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


# ─── 의존성: 권한 체크 ───────────────────────────────────────────
def require_admin(x_user_role: str = Header(default="")) -> None:
    """
    api-gateway가 주입한 X-User-Role 헤더 검증.

    주의: product-service는 JWT를 직접 검증하지 않는다.
    api-gateway가 이미 검증한 헤더를 신뢰하는 설계 (내부망 통신 전제).
    외부 직접 접근 시 api-gateway 없이 헤더를 위조할 수 있으므로
    운영에서는 서비스 메시(mTLS) 또는 네트워크 정책으로 보호 필수.
    """
    if x_user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )


# ─── 엔드포인트 ──────────────────────────────────────────────────


@router.get("", response_model=ProductListResponse)
async def list_products(
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    active_only: bool = Query(default=True, description="활성 상품만 조회"),
):
    """
    상품 목록 조회 (offset 페이지네이션).

    캐시 전략: 목록은 상세보다 짧은 TTL (60초).
    active_only=False는 관리자 용도이므로 캐시 미적용 (캐시 키 복잡도 증가 방지).
    """
    offset = (page - 1) * page_size
    conditions = []
    if active_only:
        conditions.append(Product.is_active.is_(True))

    # COUNT 쿼리와 SELECT 쿼리 분리 (SQLAlchemy subquery count는 느릴 수 있음)
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


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: DBSession):
    """
    상품 상세 조회.

    Cache-Aside 패턴:
    1. Redis 조회 → 히트 시 즉시 반환 (DB 불필요)
    2. 미스 시 DB 조회 → Redis 저장 → 반환
    """
    # 1. 캐시 조회
    cached = await get_cached_product(redis_client, product_id)
    if cached:
        cache_hit_counter.add(1, {"product_id": str(product_id)})
        log.debug("상품 캐시 히트", product_id=product_id)
        return ProductResponse(**cached)

    # 2. DB 조회
    cache_miss_counter.add(1, {"product_id": str(product_id)})
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

    # 3. 캐시 저장 (Pydantic → dict → JSON)
    response = ProductResponse.model_validate(product)
    await set_cached_product(
        redis_client,
        product_id,
        response.model_dump(mode="json"),
        settings.product_cache_ttl,
    )

    return response


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: DBSession,
    _: None = Depends(require_admin),  # type: ignore[assignment]
):
    """상품 등록 (admin 전용)."""
    product = Product(**payload.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)

    log.info("상품 생성 성공", product_id=product.id, name=product.name)
    return ProductResponse.model_validate(product)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: DBSession,
    _: None = Depends(require_admin),  # type: ignore[assignment]
):
    """
    상품 수정 (admin 전용) + 캐시 무효화.

    수정 후 캐시를 갱신하지 않고 삭제하는 이유:
    다음 조회 시 DB에서 최신 데이터를 가져와 자연스럽게 캐시가 채워짐.
    불필요한 캐시 쓰기(아무도 조회 안 할 수도 있음)를 줄임.
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="상품을 찾을 수 없습니다."
        )

    update_data = payload.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)

    # 캐시 무효화 (수정된 상품의 캐시 + 목록 캐시)
    await invalidate_product_cache(redis_client, product_id)
    log.info("상품 수정 성공", product_id=product_id)

    return ProductResponse.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: DBSession,
    _: None = Depends(require_admin),  # type: ignore[assignment]
):
    """
    상품 소프트 삭제 (admin 전용).

    물리 삭제 대신 is_active=False:
    - 기존 주문 이력에서 상품 정보 참조 가능
    - 삭제 후 복구 가능
    - FK 제약 위반 없음
    """
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="상품을 찾을 수 없습니다."
        )

    product.is_active = False
    await db.commit()

    await invalidate_product_cache(redis_client, product_id)
    log.info("상품 삭제 성공", product_id=product_id)


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
):
    """
    재고 차감 (order-service 전용 내부 API).

    낙관적 잠금 흐름:
    1. order-service가 상품 조회 시 받은 version을 payload에 포함
    2. UPDATE WHERE version = :expected → 다른 요청이 먼저 수정했으면 0 rows
    3. 0 rows = 충돌 → 409 반환, order-service가 재조회 후 재시도

    재고 부족 처리:
    - DB UPDATE에서 stock >= :qty 조건 포함 → 원자적 검사+차감
    - 앱 레벨 선검사(SELECT stock) → UPDATE 사이의 TOCTOU 경쟁 조건 방지
    """
    stock_deduct_counter.add(1, {"product_id": str(product_id)})

    # 낙관적 잠금 + 재고 부족 동시 처리: 단일 UPDATE 쿼리로 원자성 보장
    stmt = (
        update(Product)
        .where(
            Product.id == product_id,
            Product.is_active.is_(True),
            Product.version == payload.expected_version,  # 낙관적 잠금
            Product.stock >= payload.quantity,  # 재고 충분 검사
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
        # UPDATE가 0 rows → 원인을 구분해서 적절한 에러 반환
        # 원인 파악을 위해 현재 상태 조회
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
            stock_conflict_counter.add(1, {"product_id": str(product_id)})
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
                # order-service가 code로 충돌 vs 재고부족 구분 가능
            )

        # version은 맞는데 stock이 부족한 경우
        stock_insufficient_counter.add(1, {"product_id": str(product_id)})
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

    # 재고 차감 성공 → 캐시 무효화 (재고 수량이 변했으므로)
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
