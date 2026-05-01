"""
shared.telemetry 패키지 공개 인터페이스

각 서비스의 main.py에서 아래처럼 사용합니다:

from shared.telemetry import init_telemetry, init_logging, RequestLoggingMiddleware

# 서비스 시작 시 한 번만 호출
init_logging(service_name="order-service", log_format=settings.log_format)
init_telemetry(service_name="order-service", db_engine=engine)
"""

from shared.telemetry.custom_logging import init_logging
from shared.telemetry.middleware import RequestLoggingMiddleware
from shared.telemetry.setup import TelemetrySettings, init_telemetry

__all__ = [
    "init_telemetry",
    "init_logging",
    "TelemetrySettings",
    "RequestLoggingMiddleware",
]
