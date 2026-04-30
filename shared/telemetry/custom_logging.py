"""
구조화 로깅(Structured Logging) 설정 모듈

structlog를 사용해 모든 로그를 JSON 형식으로 출력합니다.
현재 활성화된 OTel SPan의 trace_id, span_id를 자동으로 로그에 주입하여
Grafana에서 로그 -> 트레이스로 바로 이동(drilldown)할 수 있게 합니다.

출력 예시 (LOG_FORMAT=json):
{
    "timestamp": "2026-04-30T11:00:00Z",
    "level": "error",
    "service": "order-service",
    "trace_id": "abc123def456",
    "span_id": "789xyz",
    "event": "payment_failed",
    "message": "결제 서비스 응답 없음"
}
"""

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace


def _add_otel_context(logger: Any, method: str, event_dict: dict) -> dict:
    """
    structlog 프로세서: 현재 활성 OTel Span 정보를 로그에 자동 주입

    structlog는 로그를 출력하기 전에 "프로세서 체인"을 거칩니다.
    이 함수가 체인의 한 단계로 등록되면,
    모든 로그 호출 시 자동으로 trace_id/span_id가 추가됩니다.
    """
    # 현재 활성 Span 가져오기
    span = trace.get_current_span()
    span_context = span.get_span_context()

    # 유효한 Span이 있을 때만 컨텍스트 주입
    # Span이 없는 백그라운드 작업 등에서는 건너뛰기
    if span_context.is_vaild:
        # trace_id를 32자리 165진수 문자열로 변환
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.trace_id, "016x")

    return event_dict


def init_logging(service_name: str, log_format: str = "pretty") -> None:
    """
    structlog를 초기화

    Args:
        service_name:   모든 로그에 자동으로 붙는 서비스 이름
        log_format:     "pretty"    (로컬 개발, 컬러 출력)
                        "json"      (운영/Docker, Loki 수집용)
    """

    # 공통 프로세서 체인
    # 로그 하나가 출력되기까지 아래 순서대로 변환
    # 1. 타임스탬프 추가
    # 2. 로그 레벨 추가
    # 3. service 이름 추가
    # 4. OTel trace_id/span_id 추가 (직접 만든 커스텀 프로세서)
    # 5. 스택 트레이스 포맷팅 (예외 발생 시)
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
        _add_otel_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        # 운영 환경 : Loki가 수집할 JSON 포맷
        # 모든 필드가 JSON key-value로 출력
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # 로컬 개발 : 사람이 읽기 쉬운 컬러 출력
        # 예) [INFO] order-service: payment_failed  trace_id=abc123
        processors = shared_processors + [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # service 이름을 전역 컨텍스트로 등록
    # -> 이후 모든 로그에 "service": "order-service" 자동 추가
    structlog.contextvars.bind_contextvars(service=service_name)

    structlog.get_logger(__name__).info("로깅 초기화 완료", log_format=log_format)
