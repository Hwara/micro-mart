import pytest
from app import auth as auth_utils
from app.models import User
from app.schemas import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest
from app.services.auth_service import (
    get_jwks_service,
    login_service,
    logout_service,
    refresh_service,
    register_service,
)
from fastapi import HTTPException


async def _create_user(db, email="user@example.com", password="password", **kwargs) -> User:
    """auth service 테스트에 필요한 사용자 레코드를 생성한다."""
    user = User(
        email=email,
        hashed_password=auth_utils.hash_password(password),
        role=kwargs.pop("role", "customer"),
        token_version=kwargs.pop("token_version", 0),
        is_active=kwargs.pop("is_active", True),
        **kwargs,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_register_service_creates_default_customer(db_session) -> None:
    """회원가입이 기본 customer 계정과 안전한 password hash를 생성하는지 확인한다."""
    result = await register_service(
        RegisterRequest(email="new@example.com", password="password"),
        db_session,
    )

    user = await db_session.get(User, result["user_id"])
    assert result == {"user_id": user.id, "email": "new@example.com"}
    assert user.hashed_password != "password"
    assert user.role == "customer"
    assert user.token_version == 0
    assert user.is_active is True


@pytest.mark.asyncio
async def test_register_service_rejects_duplicate_email(db_session) -> None:
    """이미 존재하는 이메일로 회원가입하면 409가 반환되는지 확인한다."""
    await _create_user(db_session)

    with pytest.raises(HTTPException) as exc:
        await register_service(
            RegisterRequest(email="user@example.com", password="password"), db_session
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_login_service_success_stores_refresh_by_device(db_session, fake_redis) -> None:
    """정상 로그인 시 access token과 device별 refresh token이 발급되는지 확인한다."""
    user = await _create_user(db_session, password="correct")

    response = await login_service(
        LoginRequest(email=user.email, password="correct", device="phone"),
        db_session,
    )

    assert response.token_type == "bearer"
    assert auth_utils.decode_access_token(response.access_token)["sub"] == str(user.id)
    assert fake_redis.values["refresh:user:1:phone"] == response.refresh_token


@pytest.mark.asyncio
async def test_login_service_rejects_missing_wrong_and_inactive_users(db_session) -> None:
    """로그인 실패 경로가 계정 존재 여부를 숨기고 비활성 사용자를 차단하는지 확인한다."""
    await _create_user(db_session, email="inactive@example.com", is_active=False)
    await _create_user(db_session, email="active@example.com", password="correct")

    for body in [
        LoginRequest(email="missing@example.com", password="anything"),
        LoginRequest(email="active@example.com", password="wrong"),
    ]:
        with pytest.raises(HTTPException) as exc:
            await login_service(body, db_session)
        assert exc.value.status_code == 401
        assert exc.value.detail == "이메일 또는 비밀번호가 올바르지 않습니다."

    with pytest.raises(HTTPException) as exc:
        await login_service(
            LoginRequest(email="inactive@example.com", password="password"), db_session
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_refresh_service_rotates_tokens(db_session, fake_redis) -> None:
    """정상 refresh가 access token을 재발급하고 refresh token을 회전하는지 확인한다."""
    user = await _create_user(db_session)
    old = await auth_utils.create_refresh_token(fake_redis, user.id, "web")

    response = await refresh_service(RefreshRequest(refresh_token=old), db_session)

    assert response.refresh_token != old
    assert fake_redis.values[f"refresh:token:{old}"] == "REVOKED:1:web"
    assert auth_utils.decode_access_token(response.access_token)["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_refresh_service_rejects_missing_tombstone_mismatch_and_inactive(
    db_session,
    fake_redis,
) -> None:
    """누락, tombstone, 저장값 불일치, 비활성 사용자 refresh가 401인지 확인한다."""
    user = await _create_user(db_session)

    with pytest.raises(HTTPException) as exc:
        await refresh_service(RefreshRequest(refresh_token="missing"), db_session)
    assert exc.value.status_code == 401

    old = await auth_utils.create_refresh_token(fake_redis, user.id, "web")
    await auth_utils.rotate_refresh_token(fake_redis, user.id, "web")
    with pytest.raises(HTTPException) as exc:
        await refresh_service(RefreshRequest(refresh_token=old), db_session)
    assert exc.value.status_code == 401
    assert "refresh:user:1:web" not in fake_redis.values

    mismatch = await auth_utils.create_refresh_token(fake_redis, user.id, "web")
    fake_redis.values["refresh:user:1:web"] = "different"
    with pytest.raises(HTTPException) as exc:
        await refresh_service(RefreshRequest(refresh_token=mismatch), db_session)
    assert exc.value.status_code == 401
    assert "refresh:user:1:web" not in fake_redis.values

    inactive = await _create_user(db_session, email="off@example.com", is_active=False)
    inactive_token = await auth_utils.create_refresh_token(fake_redis, inactive.id, "web")
    with pytest.raises(HTTPException) as exc:
        await refresh_service(RefreshRequest(refresh_token=inactive_token), db_session)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_service_rejects_deleted_user(db_session, fake_redis) -> None:
    """Redis에는 있지만 DB에 없는 사용자의 refresh token은 거부되는지 확인한다."""
    await fake_redis.setex("refresh:token:orphan", 60, "999:web")
    await fake_redis.setex("refresh:user:999:web", 60, "orphan")

    with pytest.raises(HTTPException) as exc:
        await refresh_service(RefreshRequest(refresh_token="orphan"), db_session)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_service_revokes_matching_refresh_token(db_session, fake_redis) -> None:
    """access token 사용자와 refresh token 소유자가 같으면 현재 session을 폐기하는지 확인한다."""
    user = await _create_user(db_session)
    access = auth_utils.create_access_token(user)
    refresh = await auth_utils.create_refresh_token(fake_redis, user.id, "web")

    await logout_service(LogoutRequest(refresh_token=refresh), access)

    assert "refresh:user:1:web" not in fake_redis.values
    assert fake_redis.values[f"refresh:token:{refresh}"] == "REVOKED:1:web"


@pytest.mark.asyncio
async def test_logout_service_invalid_or_mismatched_tokens(db_session, fake_redis) -> None:
    """logout이 invalid access token과 소유자 불일치 refresh token을 차단하는지 확인한다."""
    user = await _create_user(db_session)
    other = await _create_user(db_session, email="other@example.com")
    access = auth_utils.create_access_token(user)
    other_refresh = await auth_utils.create_refresh_token(fake_redis, other.id, "web")

    with pytest.raises(HTTPException) as exc:
        await logout_service(LogoutRequest(refresh_token=other_refresh), access)
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        await logout_service(LogoutRequest(refresh_token="missing"), "not-a-jwt")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_service_ignores_missing_or_rotated_refresh_token(
    db_session, fake_redis
) -> None:
    """이미 없거나 회전된 refresh token logout은 조용히 성공하는지 확인한다."""
    user = await _create_user(db_session)
    access = auth_utils.create_access_token(user)
    refresh = await auth_utils.create_refresh_token(fake_redis, user.id, "web")
    await auth_utils.rotate_refresh_token(fake_redis, user.id, "web")

    await logout_service(LogoutRequest(refresh_token="missing"), access)
    await logout_service(LogoutRequest(refresh_token=refresh), access)


def test_get_jwks_service_returns_public_key_only() -> None:
    """JWKS 응답이 public key 필드만 포함하고 private key를 노출하지 않는지 확인한다."""
    jwks = get_jwks_service()
    key = jwks["keys"][0]

    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"] == "micromart-key-1"
    assert key["n"]
    assert key["e"]
    assert "d" not in key
