"""
payment-service 환경변수 설정

Chaos Mode 변수(CHAOS_*)는 선택적이며 기본값으로 비활성화됨.
운영 배포 시 CHAOS_* 변수를 모두 기본값(0, false)으로 유지.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_path, extra="ignore", env_file_encoding="utf-8")

    # 서비스 식별
    service_name: str = "payment-service"
    service_version: str = "0.1.0"
    debug: bool = False

    # DB: payment-db 독립 인스턴스
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/paymentdb"

    # 내부 서비스 토큰 (order-service → payment-service 호출 인증)
    internal_service_token: str

    # OTel
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_format: str = "json"

    # ── Chaos Mode ──
    # CHAOS_FAILURE_RATE: 0.0 ~ 1.0 (0.3 = 30% 확률로 결제 실패)
    chaos_failure_rate: float = 0.0
    # CHAOS_LATENCY_MS: 결제 처리 전 강제 지연 (밀리초)
    chaos_latency_ms: int = 0
    # CHAOS_DB_SLOWQUERY: DB 슬로우쿼리 시뮬레이션 (조회 전 추가 지연)
    chaos_db_slowquery: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
