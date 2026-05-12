"""
notification-service 설정.

DB/Redis 없는 stateless consumer 서비스이며, NATS order.completed 구독과
알림 발송 시뮬레이션 설정만 환경변수로 관리한다.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """notification-service 런타임 설정."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "notification-service"
    service_version: str = "0.1.0"
    debug: bool = False
    log_format: str = "json"

    nats_url: str = "nats://nats:4222"
    nats_subject_order_completed: str = "order.completed"
    nats_connect_timeout_seconds: int = 5

    notification_send_delay_ms: int = Field(default=0, ge=0)
    notification_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_insecure: bool = True


@lru_cache
def get_settings() -> Settings:
    """환경변수에서 Settings를 한 번 로딩해 재사용한다."""
    return Settings()
