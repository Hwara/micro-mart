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
from typing import Any

import structlog


def init_logging(service_name: str, log_format: str = "pretty") -> None:
    """
    structlog를 초기화

    Args:
        service_name:   모든 로그에 자동으로 붙는 서비스 이름
        log_format:     "pretty"    (로컬 개발, 컬러 출력)
                        "json"      (운영/Docker, Loki 수집용)
    """

    # log_format 검증
    if log_format not in {"pretty", "json"}:
        raise ValueError("log_format must be one of: 'pretty', 'json'")

    # 공통 프로세서 체인
    # 로그 하나가 출력되기까지 아래 순서대로 변환
    # 1. 타임스탬프 추가
    # 2. 로그 레벨 추가
    # 3. service 이름 추가
    # 4. 스택 트레이스 포맷팅 (예외 발생 시)
    # trace_id 및 span_id는 LoggingInstrumentor 에서 자동으로 추가
    shared_processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.contextvars.merge_contextvars,
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
        # stdlib logging을 통해야 OTel LoggingHandler가 OTLP로 전달할 수 있음
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # service 이름을 전역 컨텍스트로 등록
    # -> 이후 모든 로그에 "service": "order-service" 자동 추가
    structlog.contextvars.bind_contextvars(service=service_name)

    structlog.get_logger(__name__).info("로깅 초기화 완료", log_format=log_format)
