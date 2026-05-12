from datetime import UTC, datetime

import pytest
from app import auth as auth_utils
from app.config import get_settings
from app.models import User
from jose import JWTError, jwt


def test_hash_and_verify_password() -> None:
    hashed = auth_utils.hash_password("secret-password")

    assert hashed != "secret-password"
    assert auth_utils.verify_password("secret-password", hashed) is True
    assert auth_utils.verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token_contains_required_claims() -> None:
    user = User(
        id=7, email="user@example.com", hashed_password="hash", role="admin", token_version=3
    )

    token = auth_utils.create_access_token(user)
    payload = auth_utils.decode_access_token(token)

    assert payload["sub"] == "7"
    assert payload["role"] == "admin"
    assert payload["token_version"] == 3
    assert "iat" in payload
    assert "exp" in payload
    assert payload["exp"] > int(datetime.now(UTC).timestamp())


def test_decode_access_token_rejects_invalid_signature() -> None:
    settings = get_settings()
    token = jwt.encode({"sub": "1"}, settings.jwt_private_key, algorithm=settings.jwt_algorithm)
    tampered = f"{token[:-1]}x"

    with pytest.raises(JWTError):
        auth_utils.decode_access_token(tampered)


@pytest.mark.asyncio
async def test_create_refresh_token_stores_forward_and_reverse_keys(fake_redis) -> None:
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == token
    assert fake_redis.values[f"refresh:token:{token}"] == "1:web"


@pytest.mark.asyncio
async def test_create_refresh_token_deletes_previous_reverse_key(fake_redis) -> None:
    old = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    new = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == new
    assert f"refresh:token:{old}" not in fake_redis.values
    assert fake_redis.values[f"refresh:token:{new}"] == "1:web"


@pytest.mark.asyncio
async def test_verify_refresh_token_matches_stored_token(fake_redis) -> None:
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert await auth_utils.verify_refresh_token(fake_redis, 1, token, "web") is True
    assert await auth_utils.verify_refresh_token(fake_redis, 1, "other-token", "web") is False
    assert await auth_utils.verify_refresh_token(fake_redis, 2, token, "web") is False


@pytest.mark.asyncio
async def test_rotate_refresh_token_tombstones_previous_reverse_key(fake_redis) -> None:
    old = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    new = await auth_utils.rotate_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == new
    assert fake_redis.values[f"refresh:token:{old}"] == "REVOKED:1:web"
    assert fake_redis.values[f"refresh:token:{new}"] == "1:web"

    with pytest.raises(auth_utils.TokenReusedException):
        await auth_utils.get_user_id_from_refresh_token(fake_redis, old)


@pytest.mark.asyncio
async def test_revoke_refresh_token_removes_forward_and_keeps_tombstone(fake_redis) -> None:
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="mobile")

    await auth_utils.revoke_refresh_token(fake_redis, user_id=1, device="mobile")

    assert "refresh:user:1:mobile" not in fake_redis.values
    assert fake_redis.values[f"refresh:token:{token}"] == "REVOKED:1:mobile"


@pytest.mark.asyncio
async def test_revoke_all_refresh_tokens_removes_user_sessions(fake_redis) -> None:
    web = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    mobile = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="mobile")
    other = await auth_utils.create_refresh_token(fake_redis, user_id=2, device="web")

    await auth_utils.revoke_all_refresh_tokens(fake_redis, user_id=1)

    assert "refresh:user:1:web" not in fake_redis.values
    assert "refresh:user:1:mobile" not in fake_redis.values
    assert f"refresh:token:{web}" not in fake_redis.values
    assert f"refresh:token:{mobile}" not in fake_redis.values
    assert fake_redis.values["refresh:user:2:web"] == other
