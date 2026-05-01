"""
JWT 발급 및 Refresh Token 관리

이 파일이 user-service의 인증 핵심 로직입니다.
개인키(private key)를 직접 다루는 유일한 모듈입니다.
"""

import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import User

settings = get_settings()

# ── 비밀번호 해싱 설정 ──
# bcrypt: 현재 표준 해싱 알고리즘. rounds가 높을수록 안전하지만 느림
# deprecated="auto": 오래된 해시는 자동으로 재해싱
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ════════════════════════════════════════
# 비밀번호 유틸리티
# ════════════════════════════════════════


def hash_password(plain_password: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환"""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """평문 비밀번호와 저장된 해시를 비교"""
    return pwd_context.verify(plain_password, hashed_password)


# ════════════════════════════════════════
# Access Token (JWT)
# ════════════════════════════════════════


def create_access_token(user: User) -> str:
    """
    RS256 Access Token 생성 (TTL: 15분)

    Payload 구조:
        sub: 사용자 ID (subject)
        role: 권한 (customer | admin)
        token_version: 현재 버전. api-gateway가 Refresh 요청 시 검증
        iat: 발급 시각
        exp: 만료 시각
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "token_version": user.token_version,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_private_key,  # 개인키로 서명
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict:
    """
    Access Token 디코딩 및 검증
    만료되었거나 서명이 유효하지 않으면 JWTError 발생
    """
    return jwt.decode(
        token,
        settings.jwt_public_key,  # 공개키로 검증
        algorithms=[settings.jwt_algorithm],
    )


# ════════════════════════════════════════
# Refresh Token (Redis)
# ════════════════════════════════════════


def _refresh_token_key(user_id: int, device: str) -> str:
    """
    Redis 키 네이밍 규칙: refresh:user:{id}:{device}
    device는 클라이언트 기기 식별자 (예: "web", "mobile-ios")
    기기별로 독립적인 세션을 관리할 수 있음
    """
    return f"refresh:user:{user_id}:{device}"


async def create_refresh_token(
    redis: aioredis.Redis,
    user_id: int,
    device: str = "web",
) -> str:
    """
    Refresh Token 생성 및 Redis 저장

    Refresh Token 자체는 단순한 UUID입니다.
    진짜 검증은 Redis에 저장된 값과 비교하는 방식입니다.
    (JWT 형식이 아닌 이유: 서버 측에서 즉시 무효화가 가능해야 하기 때문)

    토큰을 통해 인증된 user_id를 역조회를 위한 키 추가
    """
    token = str(uuid.uuid4())
    key = _refresh_token_key(user_id, device)
    reverse_key = f"refresh:token:{token}"  # 역조회용 키 추가
    expire_seconds = settings.refresh_token_expire_days * 24 * 60 * 60

    # 기존 토큰의 역방향 키 정리
    # 같은 기기로 재로그인 시 이전 역방향 키가 고아로 남는 것을 방지
    existing_token = await redis.get(key)

    # 두 키를 원자적으로 저장
    async with redis.pipeline() as pipe:
        # 기존 역방향 키 삭제 (존재하는 경우에만)
        if existing_token:
            pipe.delete(f"refresh:token:{existing_token}")

        # 새 정방향 + 역방향 키 저장
        pipe.setex(key, expire_seconds, token)
        pipe.setex(reverse_key, expire_seconds, f"{user_id}:{device}")
        await pipe.execute()
    return token


async def verify_refresh_token(
    redis: aioredis.Redis,
    user_id: int,
    token: str,
    device: str = "web",
) -> bool:
    """
    Redis에 저장된 Refresh Token과 제출된 토큰을 비교

    토큰이 없거나(삭제됨) 값이 다르면 False 반환
    → 재사용 감지 로직의 핵심
    """
    key = _refresh_token_key(user_id, device)
    stored_token = await redis.get(key)

    if stored_token is None:
        # 이미 삭제된 토큰으로 접근 → 재사용 시도 감지
        return False

    return stored_token == token


async def revoke_refresh_token(
    redis: aioredis.Redis,
    user_id: int,
    device: str = "web",
) -> None:
    """로그아웃: 정방향 + 역방향 키 모두 삭제"""
    key = _refresh_token_key(user_id, device)
    stored_token = await redis.get(key)

    async with redis.pipeline() as pipe:
        pipe.delete(key)
        if stored_token:
            pipe.delete(f"refresh:token:{stored_token}")
        await pipe.execute()


async def revoke_all_refresh_tokens(
    redis: aioredis.Redis,
    user_id: int,
) -> None:
    """
    해당 사용자의 모든 기기 Refresh Token 삭제
    정방향 키(refresh:user:{id}:{device})와
    역방향 키(refresh:token:{value}) 모두 삭제합니다.
    """
    pattern = f"refresh:user:{user_id}:*"
    forward_keys = []
    token_values = []

    # 1단계: 정방향 키를 스캔하면서 토큰 값도 함께 수집
    async for key in redis.scan_iter(pattern):
        forward_keys.append(key)
        token_value = await redis.get(key)
        if token_value:
            token_values.append(f"refresh:token:{token_value}")

    if not forward_keys:
        return

    # 2단계: 정방향 + 역방향 키 한 번에 삭제 (pipeline으로 원자적 처리)
    async with redis.pipeline() as pipe:
        pipe.delete(*forward_keys)
        if token_values:
            pipe.delete(*token_values)
        await pipe.execute()


# ════════════════════════════════════════
# 사용자 조회 유틸리티
# ════════════════════════════════════════


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_id_from_refresh_token(
    redis: aioredis.Redis,
    token: str,
) -> tuple[int, str] | None:
    """
    토큰 값으로 (user_id, device) 역조회
    존재하지 않으면 None 반환
    """
    value = await redis.get(f"refresh:token:{token}")
    if not value:
        return None
    user_id_str, device = value.split(":", 1)
    return int(user_id_str), device
