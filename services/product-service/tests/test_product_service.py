from datetime import UTC, datetime, timedelta

import pytest
from app.models import Product
from app.schemas import ProductCreate, ProductUpdate, StockDeductRequest, StockRestoreRequest
from app.services.product_service import (
    create_product_service,
    deduct_stock_service,
    delete_product_service,
    get_product_service,
    list_products_service,
    restore_stock_service,
    update_product_service,
)
from fastapi import HTTPException
from pydantic import ValidationError


async def _create_product(db, **kwargs) -> Product:
    """product service 테스트에 필요한 상품 레코드를 생성한다."""
    product = Product(
        name=kwargs.pop("name", "Keyboard"),
        description=kwargs.pop("description", "Tactile"),
        price=kwargs.pop("price", 1000),
        stock=kwargs.pop("stock", 10),
        version=kwargs.pop("version", 1),
        is_active=kwargs.pop("is_active", True),
        created_at=kwargs.pop("created_at", datetime.now(UTC)),
        updated_at=kwargs.pop("updated_at", datetime.now(UTC)),
        **kwargs,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@pytest.mark.asyncio
async def test_list_products_filters_permissions_paginates_and_sorts(db_session) -> None:
    """상품 목록 조회가 active filter, 권한, pagination, 최신순 정렬을 지키는지 확인한다."""
    now = datetime.now(UTC)
    oldest = await _create_product(db_session, name="Old", created_at=now - timedelta(days=2))
    newest = await _create_product(db_session, name="New", created_at=now)
    inactive = await _create_product(
        db_session,
        name="Hidden",
        is_active=False,
        created_at=now - timedelta(days=1),
    )

    response = await list_products_service(
        db_session, "customer", page=1, page_size=1, active_only=True
    )
    assert response.total == 2
    assert response.has_next is True
    assert response.items[0].id == newest.id

    page_two = await list_products_service(
        db_session, "customer", page=2, page_size=1, active_only=True
    )
    assert page_two.items[0].id == oldest.id
    assert page_two.has_next is False

    admin = await list_products_service(
        db_session, "admin", page=1, page_size=10, active_only=False
    )
    assert {item.id for item in admin.items} == {oldest.id, newest.id, inactive.id}

    with pytest.raises(HTTPException) as exc:
        await list_products_service(db_session, "customer", page=1, page_size=10, active_only=False)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_product_uses_cache_or_db_fallback(db_session, fake_redis) -> None:
    """상품 상세 조회가 cache hit, DB fallback, cache 저장 실패를 안전하게 처리하는지 확인한다."""
    product = await _create_product(db_session)
    fake_redis.values[f"product:detail:{product.id}"] = product_response_json(product)

    cached = await get_product_service(product.id, db_session)
    assert cached.id == product.id

    await fake_redis.delete(f"product:detail:{product.id}")
    db_result = await get_product_service(product.id, db_session)
    assert db_result.id == product.id
    assert f"product:detail:{product.id}" in fake_redis.values

    fake_redis.fail_get = True
    fallback = await get_product_service(product.id, db_session)
    assert fallback.id == product.id

    fake_redis.fail_setex = True
    assert (await get_product_service(product.id, db_session)).id == product.id


def product_response_json(product: Product) -> str:
    """ProductResponse 캐시 hit 테스트에 사용할 JSON 문자열을 만든다."""
    return (
        "{"
        f'"id": {product.id}, "name": "{product.name}", "description": "{product.description}", '
        f'"price": {product.price}, "stock": {product.stock}, "version": {product.version}, '
        f'"is_active": true, "created_at": "{product.created_at.isoformat()}", '
        f'"updated_at": "{product.updated_at.isoformat()}"'
        "}"
    )


@pytest.mark.asyncio
async def test_get_product_rejects_missing_or_inactive_products(db_session) -> None:
    """상품 상세 조회가 미존재 또는 비활성 상품을 404로 차단하는지 확인한다."""
    inactive = await _create_product(db_session, is_active=False)

    for product_id in [999, inactive.id]:
        with pytest.raises(HTTPException) as exc:
            await get_product_service(product_id, db_session)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_product_defaults_and_schema_validation(db_session) -> None:
    """상품 생성 기본값과 schema validation 실패 경계를 확인한다."""
    response = await create_product_service(
        ProductCreate(name="Mouse", description=None, price=500, stock=3),
        db_session,
    )

    product = await db_session.get(Product, response.id)
    assert product.version == 1
    assert product.is_active is True

    for payload in [
        {"name": "Bad", "description": None, "price": 0, "stock": 1},
        {"name": "Bad", "description": None, "price": 100, "stock": -1},
        {"name": "", "description": None, "price": 100, "stock": 1},
    ]:
        with pytest.raises(ValidationError):
            ProductCreate(**payload)


@pytest.mark.asyncio
async def test_update_product_changes_only_given_fields_and_invalidates_cache(
    db_session, fake_redis
) -> None:
    """상품 수정이 지정 필드만 바꾸고 캐시를 무효화하는지 확인한다."""
    product = await _create_product(db_session, name="Before", price=100, stock=5)

    response = await update_product_service(
        product.id, ProductUpdate(price=200, is_active=False), db_session
    )

    assert response.price == 200
    assert response.name == "Before"
    assert response.stock == 5
    assert response.is_active is False
    assert f"product:detail:{product.id}" in fake_redis.deleted

    with pytest.raises(HTTPException) as exc:
        await update_product_service(999, ProductUpdate(price=200), db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_product_soft_deletes_and_invalidates_cache(db_session, fake_redis) -> None:
    """상품 삭제가 soft delete로 동작하고 상세 조회와 캐시를 갱신하는지 확인한다."""
    product = await _create_product(db_session)

    await delete_product_service(product.id, db_session)
    await db_session.refresh(product)

    assert product.is_active is False
    assert f"product:detail:{product.id}" in fake_redis.deleted

    with pytest.raises(HTTPException) as exc:
        await get_product_service(product.id, db_session)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await delete_product_service(999, db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deduct_stock_success_conflicts_and_state_integrity(db_session, fake_redis) -> None:
    """재고 차감 성공과 실패 시 stock/version 정합성을 확인한다."""
    product = await _create_product(db_session, stock=5, version=1)

    response = await deduct_stock_service(
        product.id,
        StockDeductRequest(quantity=2, expected_version=1),
        db_session,
    )
    assert response.product_id == product.id
    assert response.remaining_stock == 3
    assert response.new_version == 2
    assert f"product:detail:{product.id}" in fake_redis.deleted

    with pytest.raises(HTTPException) as exc:
        await deduct_stock_service(
            product.id, StockDeductRequest(quantity=1, expected_version=1), db_session
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "VERSION_CONFLICT"

    await db_session.refresh(product)
    assert product.stock == 3
    assert product.version == 2

    with pytest.raises(HTTPException) as exc:
        await deduct_stock_service(
            product.id, StockDeductRequest(quantity=99, expected_version=2), db_session
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "INSUFFICIENT_STOCK"

    await db_session.refresh(product)
    assert product.stock == 3
    assert product.version == 2


@pytest.mark.asyncio
async def test_deduct_stock_rejects_missing_inactive_and_duplicate_version(db_session) -> None:
    """재고 차감이 미존재, 비활성, 같은 version 재사용을 거부하는지 확인한다."""
    active = await _create_product(db_session, stock=2, version=1)
    inactive = await _create_product(db_session, is_active=False)

    await deduct_stock_service(
        active.id, StockDeductRequest(quantity=1, expected_version=1), db_session
    )
    with pytest.raises(HTTPException) as exc:
        await deduct_stock_service(
            active.id, StockDeductRequest(quantity=1, expected_version=1), db_session
        )
    assert exc.value.status_code == 409

    for product_id in [999, inactive.id]:
        with pytest.raises(HTTPException) as exc:
            await deduct_stock_service(
                product_id, StockDeductRequest(quantity=1, expected_version=1), db_session
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_restore_stock_success_without_expected_version(db_session, fake_redis) -> None:
    """재고 복구가 expected_version 없이 stock과 version을 증가시키는지 확인한다."""
    product = await _create_product(db_session, stock=1, version=4)

    response = await restore_stock_service(product.id, StockRestoreRequest(quantity=3), db_session)

    assert response.remaining_stock == 4
    assert response.new_version == 5
    assert f"product:detail:{product.id}" in fake_redis.deleted


@pytest.mark.asyncio
async def test_restore_stock_rejects_missing_or_inactive(db_session) -> None:
    """재고 복구가 미존재 또는 비활성 상품을 404로 차단하는지 확인한다."""
    inactive = await _create_product(db_session, is_active=False)

    for product_id in [999, inactive.id]:
        with pytest.raises(HTTPException) as exc:
            await restore_stock_service(product_id, StockRestoreRequest(quantity=1), db_session)
        assert exc.value.status_code == 404
