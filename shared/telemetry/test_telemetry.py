"""
shared/telemetry 동작 확인 스크립트
실제 OTel Collector 없이도 초기화 오류 여부를 검증합니다.
"""

import os
import sys

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import structlog

from shared.telemetry import TelemetrySettings, init_logging, init_telemetry


def _test_logging():
    print("\n=== 로깅 초기화 테스트 ===")
    init_logging(service_name="test-service", log_format="pretty")
    logger = structlog.get_logger()
    logger.info("로깅 테스트", key="value", number=42)
    logger.warning("경고 테스트", reason="테스트 목적")
    print("✅ 로깅 초기화 성공")


def _test_telemetry():
    print("\n=== OTel 초기화 테스트 ===")
    # 실제 Collector가 없어도 초기화는 성공합니다
    # (Exporter가 연결 실패해도 앱은 정상 동작하도록 설계됨)
    settings = TelemetrySettings(otel_exporter_otlp_endpoint="http://localhost:4317")
    init_telemetry(service_name="test-service", settings=settings)
    print("✅ OTel 초기화 성공")


def _test_trace_id_injection():
    print("\n=== trace_id 주입 테스트 ===")
    from opentelemetry import trace

    # 테스트용 TracerProvider (이미 위에서 초기화됨)
    tracer = trace.get_tracer("test")
    logger = structlog.get_logger()

    with tracer.start_as_current_span("test-span"):
        logger.info("Span 내부 로그 (trace_id가 포함되어야 함)")

    logger.info("Span 외부 로그 (trace_id가 없어야 함)")
    print("✅ trace_id 주입 테스트 완료 (위 로그에서 trace_id 확인)")


if __name__ == "__main__":
    _test_logging()
    _test_telemetry()
    _test_trace_id_injection()
    print("\n🎉 모든 테스트 통과!")
