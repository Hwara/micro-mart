"""
product-service 환경변수 설정

pydantic-settings는 클래스 필드와 동일한 이름의 환경변수를 자동으로 읽음
예) DATABASE_URL 환경변수 -> database_url 필드에 자동 매핑
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # 서비스 식별
    service_name: str = "product-service"
    service_version: str = "0.1.0"
    debug: bool = False
    log_format: str = "json"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = False

    # DB: infra.yaml의 productdb 연결
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/productdb"

    # Redis: user-service와 동일 인스턴스, 다른 키 네임스페이스로 격리
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_connect_timeout: float = 1.0
    redis_socket_timeout: float = 1.0

    # 캐시 TTL: 상품 데이터는 자주 변하지 않으므로 5분으로 설정
    # 너무 길면 수정 후 반영이 늦고, 너무 짧으면 캐시 효과가 없음
    product_cache_ttl: int = 300  # seconds

    # 내부 서비스 토큰
    internal_service_token: str

    @field_validator("internal_service_token")
    @classmethod
    def validate_internal_service_token(cls, value: str) -> str:
        """
        Fail fast when INTERNAL_SERVICE_TOKEN is empty.

        verify_internal_service still checks the runtime header value, but the
        service should not start with an unusable shared secret.
        """
        if not value.strip():
            raise ValueError("INTERNAL_SERVICE_TOKEN must not be empty")
        return value

    # 페이지네이션 기본값
    default_page_size: int = 20
    max_page_size: int = 100


# lru_cache: Settings 객체를 한 번만 생성하고 재사용
# 환경변수를 매번 읽지 않아도 되므로 성능상 이점이 있음
@lru_cache
def get_settings() -> Settings:
    return Settings()
