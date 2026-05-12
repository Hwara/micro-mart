import pytest


@pytest.mark.asyncio
async def test_register_route_success_and_validation(client) -> None:
    response = await client.post(
        "/auth/register", json={"email": "new@example.com", "password": "pw"}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"

    assert (
        await client.post("/auth/register", json={"email": "bad", "password": "pw"})
    ).status_code == 422
    assert (
        await client.post("/auth/register", json={"email": "new2@example.com"})
    ).status_code == 422


@pytest.mark.asyncio
async def test_login_refresh_logout_routes(client) -> None:
    await client.post("/auth/register", json={"email": "route@example.com", "password": "pw"})

    login = await client.post(
        "/auth/login",
        json={"email": "route@example.com", "password": "pw", "device": "web"},
    )
    assert login.status_code == 200
    tokens = login.json()
    assert set(tokens) == {"access_token", "refresh_token", "token_type"}

    assert (
        await client.post("/auth/login", json={"email": "bad", "password": "pw"})
    ).status_code == 422
    assert (
        await client.post("/auth/login", json={"email": "route@example.com"})
    ).status_code == 422

    refreshed = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    rotated = refreshed.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    assert (await client.post("/auth/refresh", json={})).status_code == 422

    missing_auth = await client.post(
        "/auth/logout", json={"refresh_token": rotated["refresh_token"]}
    )
    assert missing_auth.status_code in {401, 403}

    logout = await client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert logout.status_code == 204


@pytest.mark.asyncio
async def test_jwks_route(client) -> None:
    response = await client.get("/auth/jwks")

    assert response.status_code == 200
    assert "keys" in response.json()
