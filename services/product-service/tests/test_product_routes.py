import pytest


async def _route_create(client, name="Keyboard", stock=10):
    """route 테스트에서 사용할 상품을 admin API로 생성한다."""
    response = await client.post(
        "/products",
        headers={"X-User-Role": "admin"},
        json={"name": name, "description": "Tactile", "price": 1000, "stock": stock},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_list_products_route(client) -> None:
    """상품 목록 route의 pagination validation과 active_only 권한 경계를 확인한다."""
    await _route_create(client)
    inactive = await _route_create(client, name="Hidden")
    await client.put(
        f"/products/{inactive['id']}",
        headers={"X-User-Role": "admin"},
        json={"is_active": False},
    )

    assert (await client.get("/products")).status_code == 200
    assert (await client.get("/products?page=0")).status_code == 422
    assert (await client.get("/products?page_size=101")).status_code == 422
    assert (
        await client.get("/products?active_only=false", headers={"X-User-Role": "customer"})
    ).status_code == 403
    assert (
        await client.get("/products?active_only=false", headers={"X-User-Role": "admin"})
    ).status_code == 200


@pytest.mark.asyncio
async def test_get_product_route(client) -> None:
    """상품 상세 route가 존재, 미존재, 비활성 상품을 올바른 status로 응답하는지 확인한다."""
    product = await _route_create(client)
    inactive = await _route_create(client, name="Hidden")
    await client.delete(f"/products/{inactive['id']}", headers={"X-User-Role": "admin"})

    assert (await client.get(f"/products/{product['id']}")).status_code == 200
    assert (await client.get("/products/999")).status_code == 404
    assert (await client.get(f"/products/{inactive['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_create_update_delete_admin_boundaries(client) -> None:
    """상품 생성, 수정, 삭제 route의 관리자 권한과 body validation 경계를 확인한다."""
    created = await _route_create(client)

    assert (
        await client.post(
            "/products",
            headers={"X-User-Role": "customer"},
            json={"name": "Mouse", "description": None, "price": 100, "stock": 1},
        )
    ).status_code == 403
    assert (
        await client.post(
            "/products",
            json={"name": "Mouse", "description": None, "price": 100, "stock": 1},
        )
    ).status_code == 403
    assert (
        await client.post("/products", headers={"X-User-Role": "admin"}, json={"name": ""})
    ).status_code == 422

    assert (
        await client.put(
            f"/products/{created['id']}",
            headers={"X-User-Role": "admin"},
            json={"price": 1200},
        )
    ).status_code == 200
    assert (
        await client.put(
            f"/products/{created['id']}",
            headers={"X-User-Role": "customer"},
            json={"price": 1200},
        )
    ).status_code == 403
    assert (await client.put(f"/products/{created['id']}", json={"price": 1200})).status_code == 403
    assert (
        await client.put("/products/999", headers={"X-User-Role": "admin"}, json={"price": 1200})
    ).status_code == 404
    assert (
        await client.put(
            f"/products/{created['id']}", headers={"X-User-Role": "admin"}, json={"price": 0}
        )
    ).status_code == 422

    assert (
        await client.delete(f"/products/{created['id']}", headers={"X-User-Role": "customer"})
    ).status_code == 403
    assert (await client.delete(f"/products/{created['id']}")).status_code == 403
    assert (
        await client.delete("/products/999", headers={"X-User-Role": "admin"})
    ).status_code == 404
    assert (
        await client.delete(f"/products/{created['id']}", headers={"X-User-Role": "admin"})
    ).status_code == 204


@pytest.mark.asyncio
async def test_deduct_stock_route_internal_token_and_conflicts(client) -> None:
    """재고 차감 route의 내부 토큰, validation, conflict 응답 경계를 확인한다."""
    product = await _route_create(client, stock=2)
    path = f"/products/{product['id']}/deduct-stock"

    assert (await client.post(path, json={"quantity": 1, "expected_version": 1})).status_code == 401
    assert (
        await client.post(
            path,
            headers={"X-Internal-Token": "wrong"},
            json={"quantity": 1, "expected_version": 1},
        )
    ).status_code == 401
    assert (
        await client.post(
            path,
            headers={"X-Internal-Token": "test-internal-token"},
            json={"quantity": 1},
        )
    ).status_code == 422

    ok = await client.post(
        path,
        headers={"X-Internal-Token": "test-internal-token"},
        json={"quantity": 1, "expected_version": 1},
    )
    assert ok.status_code == 200

    conflict = await client.post(
        path,
        headers={"X-Internal-Token": "test-internal-token"},
        json={"quantity": 1, "expected_version": 1},
    )
    assert conflict.status_code == 409

    insufficient = await client.post(
        path,
        headers={"X-Internal-Token": "test-internal-token"},
        json={"quantity": 5, "expected_version": 2},
    )
    assert insufficient.status_code == 409


@pytest.mark.asyncio
async def test_restore_stock_route_internal_token_and_missing_product(client) -> None:
    """재고 복구 route의 내부 토큰, validation, 미존재 상품 응답 경계를 확인한다."""
    product = await _route_create(client, stock=2)
    path = f"/products/{product['id']}/restore-stock"

    assert (await client.post(path, json={"quantity": 1})).status_code == 401
    assert (
        await client.post(path, headers={"X-Internal-Token": "wrong"}, json={"quantity": 1})
    ).status_code == 401
    assert (
        await client.post(
            path, headers={"X-Internal-Token": "test-internal-token"}, json={"quantity": 0}
        )
    ).status_code == 422
    assert (
        await client.post(
            path, headers={"X-Internal-Token": "test-internal-token"}, json={"quantity": 1}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/products/999/restore-stock",
            headers={"X-Internal-Token": "test-internal-token"},
            json={"quantity": 1},
        )
    ).status_code == 404
