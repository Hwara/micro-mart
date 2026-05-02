"""
인증 관련 API 엔드포인트

POST /auth/register  — 회원가입
POST /auth/login     — 로그인
POST /auth/refresh   — Access Token 재발급
POST /auth/logout    — 로그아웃
GET  /auth/jwks      — 공개키 JWKS (api-gateway용)
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from opentelemetry import metrics
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError

from .. import auth as auth_service
from ..config import get_settings
from ..database import DBSession, redis_client
from ..models import User

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
security = HTTPBearer()


# ── 메트릭 정의 ──────────────────────────────────────────────────
# meter: 이 서비스에서 메트릭을 발행하는 주체
# get_meter()는 MeterProvider에 등록된 전역 인스턴스를 반환
# init_telemetry()가 먼저 호출된 이후에 정상 동작합니다
meter = metrics.get_meter("user-service")

login_total = meter.create_counter(
    name="login_total",
    description="로그인 시도 횟수",
    unit="1",
    # unit="1": 단위 없는 카운트를 의미하는 OTel 표준 표기
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


# ── 요청/응답 스키마 ──────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device: str = "web"  # 기기 식별자, 기본값은 "web"


class LogoutRequest(BaseModel):
    refresh_token: str  # 로그아웃할 세션을 특정하는 유일한 식별자


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ── 엔드포인트 ────────────────────────────


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: DBSession,  # DBSession 타입 별칭 사용 (Depends(get_db) 직접 사용 금지)
):
    # 이메일 중복 선조회는 UX 목적 (빠른 피드백)으로 유지
    # 하지만 경쟁 조건 방어는 아래 IntegrityError 처리가 담당
    existing = await auth_service.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        )

    user = User(
        email=body.email,
        hashed_password=auth_service.hash_password(body.password),
    )
    db.add(user)

    try:
        await db.flush()
        # flush: SQL INSERT를 DB에 전송하되 트랜잭션은 아직 열려 있음
        # → user.id가 DB에서 채번되어 Python 객체에 반영됨
        # commit: 트랜잭션을 확정하여 실제로 저장
        # get_db()는 auto-commit을 하지 않으므로 반드시 여기서 명시적으로 호출
        await db.commit()
    except IntegrityError as e:
        # 동시 요청으로 unique 제약 조건 위반 발생 시
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        ) from e

    # 가입 완료 시점에 카운터 증가
    register_total.add(1)
    logger.info("신규 회원가입", user_id=user.id, email=user.email)
    return {"user_id": user.id, "email": user.email}


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: DBSession,
):
    # 사용자 조회 + 비밀번호 검증
    user = await auth_service.get_user_by_email(db, body.email)
    if not user or not auth_service.verify_password(body.password, user.hashed_password):
        # 실패 카운터: result="fail" 레이블로 성공과 구분
        login_total.add(1, {"result": "fail"})
        logger.warning("로그인 실패 - 잘못된 자격증명")
        # 보안: "이메일이 없음"과 "비밀번호 틀림"을 구분하지 않음
        # 구분하면 공격자가 유효한 이메일 목록을 수집할 수 있음
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    if not user.is_active:
        # 비활성 계정도 실패로 분류하되 이유를 별도 레이블로 기록
        login_total.add(1, {"result": "fail_inactive"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다.",
        )

    access_token = auth_service.create_access_token(user)
    refresh_token = await auth_service.create_refresh_token(redis_client, user.id, body.device)

    # 성공 카운터
    login_total.add(1, {"result": "success"})
    logger.info("로그인 성공", user_id=user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: DBSession,
):
    try:
        result = await auth_service.get_user_id_from_refresh_token(redis_client, body.refresh_token)
    except auth_service.TokenReusedException as e:
        # tombstone 감지 → 전체 세션 강제 종료
        logger.warning(
            "Refresh Token 재사용 감지 — 전체 세션 강제 종료",
            user_id=e.user_id,
        )
        await auth_service.revoke_all_refresh_tokens(redis_client, e.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        ) from e

    if result is None:
        # 존재하지 않는 토큰 = 이미 삭제됐거나 위조된 토큰
        logger.warning("유효하지 않은 Refresh Token 접근 시도")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        )

    user_id, token_device = result

    is_valid = await auth_service.verify_refresh_token(
        redis_client, user_id, body.refresh_token, token_device
    )

    if not is_valid:
        # 역조회는 성공했지만 값이 다른 경우 = 재사용 감지
        # 모든 세션을 즉시 강제 종료
        logger.warning(
            "Refresh Token 재사용 감지 — 전체 세션 강제 종료",
            user_id=user_id,
        )
        await auth_service.revoke_all_refresh_tokens(redis_client, user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        )

    user = await auth_service.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Refresh Token Rotation: 기존 토큰 삭제 후 새 토큰 발급
    # 같은 Refresh Token을 재사용하지 못하게 막는 핵심 메커니즘
    await auth_service.revoke_refresh_token(redis_client, user_id, token_device)
    new_access_token = auth_service.create_access_token(user)
    new_refresh_token = await auth_service.create_refresh_token(redis_client, user_id, token_device)

    # 재발급 완료 시점에 카운터 증가
    token_refresh_total.add(1)
    logger.info("토큰 재발급 완료", user_id=user.id)
    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    # Access Token에서 user_id 추출 (신원 확인)
    try:
        payload = auth_service.decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from e

    # Refresh Token 역조회로 실제 device 확인
    try:
        result = await auth_service.get_user_id_from_refresh_token(redis_client, body.refresh_token)
    except auth_service.TokenReusedException:
        # 이미 회전된 토큰 → 해당 세션은 이미 무효화되어 있음
        # 로그아웃 목적은 달성된 상태이므로 204 반환
        logger.info("로그아웃 요청: 이미 회전된 토큰", user_id=user_id)
        return

    if result is None:
        # 이미 만료됐거나 존재하지 않는 토큰
        # 로그아웃 목적은 달성됐으므로 204 반환
        return

    token_user_id, device = result

    # 토큰의 user_id와 Access Token의 user_id 일치 확인
    # 타인의 Refresh Token으로 로그아웃 시도 방지
    if token_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    await auth_service.revoke_refresh_token(redis_client, user_id, device)
    logger.info("로그아웃 완료", user_id=user_id, device=device)


@router.get("/jwks")
async def jwks():
    """
    공개키를 JWKS(JSON Web Key Set) 형식으로 반환

    api-gateway는 서비스 시작 시 이 엔드포인트를 호출하여
    공개키를 메모리에 캐싱하고 이후 JWT 검증에 사용합니다.
    """
    import base64

    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    public_key = load_pem_public_key(settings.jwt_public_key.encode())
    pub_numbers = (
        public_key.public_key().public_numbers()
        if hasattr(public_key, "public_key")
        else public_key.public_numbers()
    )

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
