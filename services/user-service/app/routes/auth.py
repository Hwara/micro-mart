"""
인증 관련 API 엔드포인트

POST /auth/register  — 회원가입
POST /auth/login     — 로그인
POST /auth/refresh   — Access Token 재발급
POST /auth/logout    — 로그아웃
GET  /auth/jwks      — 공개키 JWKS (api-gateway용)
"""

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..database import DBSession
from ..schemas import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenResponse
from ..services.auth_service import (
    get_jwks_service,
    login_service,
    logout_service,
    refresh_service,
    register_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: DBSession,
) -> dict:
    """회원가입."""
    return await register_service(body=body, db=db)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: DBSession,
) -> TokenResponse:
    """로그인."""
    return await login_service(body=body, db=db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: DBSession,
) -> TokenResponse:
    """Access Token 재발급."""
    return await refresh_service(body=body, db=db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    """로그아웃."""
    await logout_service(body=body, access_token=credentials.credentials)


@router.get("/jwks")
async def jwks() -> dict:
    """공개키를 JWKS(JSON Web Key Set) 형식으로 반환."""
    return get_jwks_service()
