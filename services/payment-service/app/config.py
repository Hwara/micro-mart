"""
payment-service 환경변수 설정

Chaos Mode 변수(CHAOS_*)는 선택적이며 기본값으로 비활성화됨.
운영 배포 시 CHAOS_* 변수를 모두 기본값(0, false)으로 유지.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # 서비스 식별
    service_name: str = "payment-service"
    service_version: str = "0.1.0"
    debug: bool = False
    log_format: str = "json"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = False

    # DB: payment-db 독립 인스턴스
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/paymentdb"
    db_pool_size: int = 5
    db_max_overflow: int = 15

    # 내부 서비스 토큰 (order-service → payment-service 호출 인증)
    internal_service_token: str

    # ── Chaos Mode ──
    # CHAOS_FAILURE_RATE: 0.0 ~ 1.0 (0.3 = 30% 확률로 결제 실패)
    chaos_failure_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="결제 실패 시뮬레이션 확률 (0.0 ~ 1.0)"
    )
    # CHAOS_LATENCY_MS: 결제 처리 전 강제 지연 (밀리초)
    chaos_latency_ms: int = Field(default=0, ge=0, description="추가 레이턴시 ms (0 이상)")
    # CHAOS_DB_SLOWQUERY: DB 슬로우쿼리 시뮬레이션 (조회 전 추가 지연)
    chaos_db_slowquery: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
