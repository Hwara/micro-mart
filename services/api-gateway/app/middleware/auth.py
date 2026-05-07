"""
JWT 검증 미들웨어

설계 핵심:
1. JWKS를 요청마다 user-service에서 가져오면 gateway가 병목 → 인메모리 캐시 사용.
2. 캐시 만료(TTL 초과) 또는 kid 미매칭 시에만 JWKS 재조회 → 캐시 무효화 방어.
3. public_key 추출은 cryptography 라이브러리로 직접 처리 (python-jose 대신).
   이유: python-jose는 유지보수가 중단되었고, PyJWT + cryptography 조합이 현업 표준.

인증이 필요 없는 경로 (PUBLIC_PATHS):
- /health: k8s liveness probe
- /auth/*: 로그인·회원가입·토큰 재발급 (JWT가 없는 상태의 요청)
- /products (GET): 비인증 상품 조회 허용
"""

import asyncio
import time

import httpx
import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

from ..config import get_settings
from .metrics import gateway_jwks_cache_counter  # 캐시 히트/미스 메트릭

logger = structlog.get_logger(__name__)

PUBLIC_PATHS: list[tuple[str | None, str]] = [
    (None, "/health"),
    (None, "/auth"),
    ("GET", "/products"),
]


class JWKSCache:
    """
    JWKS 인메모리 캐시 싱글턴.

    user-service /auth/jwks 응답을 TTL 동안 캐싱.
    kid(Key ID) 기반으로 서명 검증용 RSA 공개키를 반환.
    """

    def __init__(self) -> None:
        self._keys: dict[str, RSAPublicKey] = {}
        self._fetched_at: float = 0.0
        self._refresh_lock = asyncio.Lock()

    def _is_expired(self) -> bool:
        settings = get_settings()
        return (time.time() - self._fetched_at) > settings.jwks_cache_ttl_seconds

    async def _refresh(self) -> None:
        """user-service에서 JWKS를 가져와 캐시를 갱신한다."""
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(settings.jwks_url)
                resp.raise_for_status()
                jwks = resp.json()

            new_keys: dict[str, RSAPublicKey] = {}
            for key_data in jwks.get("keys", []):
                kid = key_data.get("kid", "default")
                public_key = RSAAlgorithm.from_jwk(key_data)
                new_keys[kid] = public_key  # type: ignore[assignment]

            self._keys = new_keys
            self._fetched_at = time.time()
            logger.info("JWKS 캐시 갱신 완료", key_count=len(new_keys))
        except Exception as e:
            logger.error("JWKS 갱신 실패", error=str(e))
            if not self._keys:
                raise

    async def get_public_key(self, kid: str | None) -> RSAPublicKey:
        """
        kid에 해당하는 공개키 반환.

        캐시 만료 또는 kid 미매칭 시 JWKS 재조회 (캐시 미스로 기록).
        kid가 None이면 첫 번째 키 반환 (단일 키 환경).
        """
        # 캐시가 살아있고 kid도 포함되면 히트
        if not self._is_expired() and self._keys:
            lookup_kid = kid or next(iter(self._keys), None)
            if lookup_kid and lookup_kid in self._keys:
                # ✅ 캐시 히트 — JWKS 재조회 없이 즉시 반환
                gateway_jwks_cache_counter.add(1, {"result": "hit"})
                return self._keys[lookup_kid]

        # 캐시 만료 또는 kid 미매칭 → 미스로 기록 후 재조회
        gateway_jwks_cache_counter.add(1, {"result": "miss"})
        async with self._refresh_lock:
            # Lock 대기 중 다른 코루틴이 이미 갱신했을 수 있으므로 재확인
            lookup_kid = kid or next(iter(self._keys), None)
            if not self._is_expired() and lookup_kid and lookup_kid in self._keys:
                logger.info("JWKS Lock 대기 후 캐시 히트 — 재조회 생략", kid=kid)
                return self._keys[lookup_kid]

            logger.info("JWKS 캐시 미스 — 재조회 시작", kid=kid, expired=self._is_expired())
            await self._refresh()

        lookup_kid = kid or next(iter(self._keys), None)
        if lookup_kid and lookup_kid in self._keys:
            return self._keys[lookup_kid]

        raise ValueError(f"공개키를 찾을 수 없습니다. kid={kid}")


jwks_cache = JWKSCache()


def is_public_path(method: str, path: str) -> bool:
    """
    인증이 필요 없는 경로인지 확인.

    path == prefix  OR  path.startswith(prefix + "/")
    → "/products" prefix는 "/products" 와 "/products/123"만 허용.
        "/products-old" 는 차단.
    """
    for allowed_method, prefix in PUBLIC_PATHS:
        if allowed_method is None or allowed_method == method:
            # 정확한 경계 매칭: /products 또는 /products/로 시작
            if path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/"):
                return True
    return False


async def verify_jwt(token: str) -> dict:
    """
    RS256 JWT 검증 후 페이로드 반환.

    1. 헤더에서 kid 추출 (서명 검증용 키 선택)
    2. JWKS 캐시에서 공개키 조회
    3. PyJWT로 서명 + 만료 + 발급자 검증

    예외:
      ValueError("expired") — 토큰 만료
      ValueError("invalid") — 서명 불일치 등
      ValueError("jwks_error") — JWKS 조회 실패
    """
    settings = get_settings()

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
    except jwt.DecodeError as e:
        raise ValueError(f"invalid:{e}") from e

    try:
        public_key = await jwks_cache.get_public_key(kid)
    except Exception as e:
        raise ValueError(f"jwks_error:{e}") from e

    audience = settings.jwt_audience if settings.jwt_audience else None

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise ValueError(f"expired:{e}") from e
    except jwt.InvalidTokenError as e:
        raise ValueError(f"invalid:{e}") from e
