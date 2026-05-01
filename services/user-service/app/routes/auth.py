"""
인증 관련 API 엔드포인트

POST /auth/register  — 회원가입
POST /auth/login     — 로그인
POST /auth/refresh   — Access Token 재발급
POST /auth/logout    — 로그아웃
GET  /auth/jwks      — 공개키 JWKS (api-gateway용)
"""

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from opentelemetry import metrics
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth as auth_service
from ..config import get_settings
from ..database import get_db, redis_client
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


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    user_id: int
    refresh_token: str
    device: str = "web"


# ── 엔드포인트 ────────────────────────────


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # 이메일 중복 확인
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
    await db.flush()  # ID를 얻기 위해 flush (커밋은 get_db에서 자동)

    # 가입 완료 시점에 카운터 증가
    register_total.add(1)
    logger.info("신규 회원가입", user_id=user.id, email=user.email)
    return {"user_id": user.id, "email": user.email}


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    # 사용자 조회 + 비밀번호 검증
    user = await auth_service.get_user_by_email(db, body.email)
    if not user or not auth_service.verify_password(body.password, user.hashed_password):
        # 실패 카운터: result="fail" 레이블로 성공과 구분
        login_total.add(1, {"result": "fail"})
        logger.warning("로그인 실패 - 잘못된 자격증명", email=body.email)
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
    db: AsyncSession = Depends(get_db),
):
    # Refresh Token 유효성 검증
    is_valid = await auth_service.verify_refresh_token(
        redis_client, body.user_id, body.refresh_token, body.device
    )

    if not is_valid:
        # 이미 삭제된 토큰으로 접근 = Refresh Token 재사용 시도
        # 모든 세션을 즉시 강제 종료
        logger.warning(
            "Refresh Token 재사용 감지 — 전체 세션 강제 종료",
            user_id=body.user_id,
        )
        await auth_service.revoke_all_refresh_tokens(redis_client, body.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 Refresh Token입니다.",
        )

    user = await auth_service.get_user_by_id(db, body.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Refresh Token Rotation: 기존 토큰 삭제 후 새 토큰 발급
    # 같은 Refresh Token을 재사용하지 못하게 막는 핵심 메커니즘
    await auth_service.revoke_refresh_token(redis_client, body.user_id, body.device)
    new_access_token = auth_service.create_access_token(user)
    new_refresh_token = await auth_service.create_refresh_token(
        redis_client, body.user_id, body.device
    )

    # 재발급 완료 시점에 카운터 증가
    token_refresh_total.add(1)
    logger.info("토큰 재발급 완료", user_id=user.id)
    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    device: str = Header(default="web", alias="X-Device"),
):
    try:
        payload = auth_service.decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from e

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
