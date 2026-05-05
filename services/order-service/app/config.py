"""
order-service 설정

order-service는 product-service, payment-service를 HTTP로 호출하므로
각 서비스 URL과 internal token을 환경변수로 관리한다.
NATS_URL은 order.completed 이벤트 발행용.
Redis 없음 → Redis 설정 포함하지 않음 (dev_convention.md 준수).
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    service_name: str = "order-service"
    service_version: str = "0.1.0"
    debug: bool = False
    log_format: str = "json"

    database_url: str

    # 서비스 간 호출용 내부 토큰 (X-Internal-Token 헤더에 사용)
    internal_service_token: str

    # 낙관적 락 충돌 시 재시도 횟수
    max_optimistic_retry: int = 3

    # 하위 서비스 URL — docker-compose 네트워크 내 서비스명으로 설정
    product_service_url: str = "http://product-service:8000"
    payment_service_url: str = "http://payment-service:8000"

    # NATS 브로커 URL — order.completed 이벤트 발행용
    nats_url: str = "nats://nats:4222"

    # 서비스 간 HTTP 호출 타임아웃 (초) — 명시적 timeout 강제 (dev_convention.md §12)
    http_timeout_seconds: float = 5.0
    nats_connect_timeout_seconds: int = 5

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
