"""
api-gateway 설정

DB 없음, Redis 없음 — stateless 서비스.
JWKS_CACHE_TTL: 공개키 캐시 유효 시간 (초). 기본 1시간.
  짧게 설정하면 키 로테이션에 빠르게 반응하지만 user-service 호출이 늘어남.
  학습 환경에서는 3600초(1시간)가 적절.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "api-gateway"
    service_version: str = "0.1.0"
    debug: bool = False
    log_format: str = "json"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = False

    # 하위 서비스 URL — docker-compose 네트워크 내 서비스명으로 설정
    user_service_url: str = "http://user-service:8000"
    product_service_url: str = "http://product-service:8000"
    order_service_url: str = "http://order-service:8000"

    # JWKS 엔드포인트 — user-service가 제공하는 RS256 공개키
    jwks_url: str = "http://user-service:8000/auth/jwks"

    # JWT 설정
    jwt_algorithm: str = "RS256"
    # audience 설정 - 빈 문자열이면 audience 검증 생략 (현재 JWT 토큰에 aud는 검증하지 않음)
    jwt_audience: str = ""

    # JWKS 캐시 TTL (초) — 공개키는 자주 바뀌지 않으므로 1시간 캐싱
    jwks_cache_ttl_seconds: int = 3600

    # 서비스 간 HTTP 호출 타임아웃 (초)
    http_timeout_seconds: float = 30.0

    # Rate Limiting — 클라이언트 IP 기준, 분당 최대 요청 수
    rate_limit_per_minute: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
