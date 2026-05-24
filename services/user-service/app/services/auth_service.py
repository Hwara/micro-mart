import base64

import structlog
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, status
from jose import JWTError
from opentelemetry import metrics
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth as auth_utils
from ..config import get_settings
from ..database import redis_client
from ..models import User
from ..schemas import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenResponse

logger = structlog.get_logger(__name__)
meter = metrics.get_meter("user-service")

login_total = meter.create_counter(
    name="login_total",
    description="로그인 시도 횟수",
    unit="1",
)
register_total = meter.create_counter(
    name="register_total",
    description="신규 회원가입 횟수",
    unit="1",
)
token_refresh_total = meter.create_counter(
    name="token_refresh_total",
    description="Access Token 재발급 횟수",
    unit="1",
)


async def register_service(body: RegisterRequest, db: AsyncSession) -> dict:
    """
    이메일 중복 검사 후 사용자를 생성한다.

    선조회는 빠른 피드백 목적이고, 동시 요청의 최종 방어는 DB unique 제약과
    IntegrityError 처리로 유지한다.
    """
    existing = await auth_utils.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        )

    user = User(
        email=body.email,
        hashed_password=auth_utils.hash_password(body.password),
    )
    db.add(user)

    try:
        await db.flush()
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        ) from e

    register_total.add(1)
    logger.info("신규 회원가입", user_id=user.id)
    return {"user_id": user.id, "email": user.email}


async def login_service(body: LoginRequest, db: AsyncSession) -> TokenResponse:
    """
    사용자 인증 후 Access Token과 기기별 Refresh Token을 발급한다.

    이메일 없음과 비밀번호 불일치를 같은 401 응답으로 처리해 계정 존재 여부가
    노출되지 않도록 기존 보안 동작을 유지한다.
    """
    user = await auth_utils.get_user_by_email(db, body.email)
    if not user or not auth_utils.verify_password(body.password, user.hashed_password):
        login_total.add(1, {"result": "fail"})
        logger.warning("로그인 실패 - 잘못된 자격증명")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    if not user.is_active:
        login_total.add(1, {"result": "fail_inactive"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다.",
        )

    access_token = auth_utils.create_access_token(user)
    refresh_token = await auth_utils.create_refresh_token(redis_client, user.id, body.device)

    login_total.add(1, {"result": "success"})
    logger.info("로그인 성공", user_id=user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh_service(body: RefreshRequest, db: AsyncSession) -> TokenResponse:
    """
    Refresh Token rotation으로 새 Access/Refresh Token을 발급한다.

    tombstone 또는 저장값 불일치가 감지되면 전체 세션을 폐기하는 기존 재사용
    감지 정책을 유지한다.
    """
    try:
        result = await auth_utils.get_user_id_from_refresh_token(redis_client, body.refresh_token)
    except auth_utils.TokenReusedException as e:
        logger.warning(
            "Refresh Token 재사용 감지 — 전체 세션 강제 종료",
            user_id=e.user_id,
        )
        await auth_utils.revoke_all_refresh_tokens(redis_client, e.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        ) from e

    if result is None:
        logger.warning("유효하지 않은 Refresh Token 접근 시도")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        )

    user_id, token_device = result
    is_valid = await auth_utils.verify_refresh_token(
        redis_client,
        user_id,
        body.refresh_token,
        token_device,
    )

    if not is_valid:
        logger.warning(
            "Refresh Token 재사용 감지 — 전체 세션 강제 종료",
            user_id=user_id,
        )
        await auth_utils.revoke_all_refresh_tokens(redis_client, user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        )

    user = await auth_utils.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    new_access_token = auth_utils.create_access_token(user)
    new_refresh_token = await auth_utils.rotate_refresh_token(redis_client, user_id, token_device)

    token_refresh_total.add(1)
    logger.info("토큰 재발급 완료", user_id=user.id)
    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


async def logout_service(body: LogoutRequest, access_token: str) -> None:
    """
    Access Token의 sub와 Refresh Token 소유자를 대조한 뒤 로그아웃한다.

    이미 만료, 삭제, 회전된 Refresh Token은 로그아웃 목적이 달성된 상태로 보고
    204 응답을 유지한다.
    """
    try:
        payload = auth_utils.decode_access_token(access_token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from e

    try:
        result = await auth_utils.get_user_id_from_refresh_token(redis_client, body.refresh_token)
    except auth_utils.TokenReusedException:
        logger.info("로그아웃 요청: 이미 회전된 토큰", user_id=user_id)
        return

    if result is None:
        return

    token_user_id, device = result
    if token_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    await auth_utils.revoke_refresh_token(redis_client, user_id, device)
    logger.info("로그아웃 완료", user_id=user_id, device=device)


def get_jwks_service() -> dict:
    """
    api-gateway JWT 검증용 공개키를 JWKS 형식으로 반환한다.

    kid와 alg는 gateway 캐시 및 검증 계약이므로 기존 값을 고정 유지한다.
    """
    settings = get_settings()

    public_key = load_pem_public_key(settings.jwt_public_key.encode())
    if not isinstance(public_key, RSAPublicKey):
        key_type = type(public_key).__name__
        logger.error(
            "JWT 공개키 타입 불일치",
            jwt_algorithm=settings.jwt_algorithm,
            key_type=key_type,
        )
        raise RuntimeError(
            f"JWT public key must be RSA for {settings.jwt_algorithm}; got {key_type}"
        )

    pub_numbers = public_key.public_numbers()

    def _int_to_base64url(n: int) -> str:
        byte_length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "micromart-key-1",
                "n": _int_to_base64url(pub_numbers.n),
                "e": _int_to_base64url(pub_numbers.e),
            }
        ]
    }
