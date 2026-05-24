from datetime import UTC, datetime

import pytest
from app import auth as auth_utils
from app.config import get_settings
from app.models import User
from jose import JWTError, jwt


def test_hash_and_verify_password() -> None:
    """비밀번호 해시가 평문과 다르고 검증 결과가 정확한지 확인한다."""
    hashed = auth_utils.hash_password("secret-password")

    assert hashed != "secret-password"
    assert auth_utils.verify_password("secret-password", hashed) is True
    assert auth_utils.verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token_contains_required_claims() -> None:
    """생성된 access token에 인증에 필요한 claim이 포함되는지 확인한다."""
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
    """서명이 변조된 access token은 decode 단계에서 거부되는지 확인한다."""
    settings = get_settings()
    token = jwt.encode({"sub": "1"}, settings.jwt_private_key, algorithm=settings.jwt_algorithm)
    signed_payload, signature = token.rsplit(".", 1)
    assert signature

    # 서명 검증 실패를 확인하기 위해 payload/header는 유지하고 signature만 변조한다.
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{signed_payload}.{replacement}{signature[1:]}"

    with pytest.raises(JWTError):
        auth_utils.decode_access_token(tampered)


@pytest.mark.asyncio
async def test_create_refresh_token_stores_forward_and_reverse_keys(fake_redis) -> None:
    """refresh token 생성 시 정방향/역방향 Redis key가 함께 저장되는지 확인한다."""
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == token
    assert fake_redis.values[f"refresh:token:{token}"] == "1:web"


@pytest.mark.asyncio
async def test_create_refresh_token_deletes_previous_reverse_key(fake_redis) -> None:
    """같은 device 재발급 시 이전 역방향 key가 고아로 남지 않는지 확인한다."""
    old = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    new = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == new
    assert f"refresh:token:{old}" not in fake_redis.values
    assert fake_redis.values[f"refresh:token:{new}"] == "1:web"


@pytest.mark.asyncio
async def test_verify_refresh_token_matches_stored_token(fake_redis) -> None:
    """저장 token과 제출 token의 일치 여부만 True로 검증되는지 확인한다."""
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")

    assert await auth_utils.verify_refresh_token(fake_redis, 1, token, "web") is True
    assert await auth_utils.verify_refresh_token(fake_redis, 1, "other-token", "web") is False
    assert await auth_utils.verify_refresh_token(fake_redis, 2, token, "web") is False


@pytest.mark.asyncio
async def test_rotate_refresh_token_tombstones_previous_reverse_key(fake_redis) -> None:
    """refresh token rotation이 이전 token을 tombstone으로 바꾸는지 확인한다."""
    old = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    new = await auth_utils.rotate_refresh_token(fake_redis, user_id=1, device="web")

    assert fake_redis.values["refresh:user:1:web"] == new
    assert fake_redis.values[f"refresh:token:{old}"] == "REVOKED:1:web"
    assert fake_redis.values[f"refresh:token:{new}"] == "1:web"

    with pytest.raises(auth_utils.TokenReusedException):
        await auth_utils.get_user_id_from_refresh_token(fake_redis, old)


@pytest.mark.asyncio
async def test_revoke_refresh_token_removes_forward_and_keeps_tombstone(fake_redis) -> None:
    """단일 refresh token 폐기 시 forward key는 삭제되고 tombstone은 유지되는지 확인한다."""
    token = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="mobile")

    await auth_utils.revoke_refresh_token(fake_redis, user_id=1, device="mobile")

    assert "refresh:user:1:mobile" not in fake_redis.values
    assert fake_redis.values[f"refresh:token:{token}"] == "REVOKED:1:mobile"


@pytest.mark.asyncio
async def test_revoke_all_refresh_tokens_removes_user_sessions(fake_redis) -> None:
    """특정 사용자의 모든 device session과 reverse key가 삭제되는지 확인한다."""
    web = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="web")
    mobile = await auth_utils.create_refresh_token(fake_redis, user_id=1, device="mobile")
    other = await auth_utils.create_refresh_token(fake_redis, user_id=2, device="web")

    await auth_utils.revoke_all_refresh_tokens(fake_redis, user_id=1)

    assert "refresh:user:1:web" not in fake_redis.values
    assert "refresh:user:1:mobile" not in fake_redis.values
    assert f"refresh:token:{web}" not in fake_redis.values
    assert f"refresh:token:{mobile}" not in fake_redis.values
    assert fake_redis.values["refresh:user:2:web"] == other
