"""
OpenTelemetry 초기화 모듈

모든 마이크로서비스가 이 모듈을 통해 OTel을 초기화합니다.
한 번 호출하면 FastAPI, SQLAlchemy, httpx의 계측이 자동으로 시작됩니다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from shared.telemetry.config import TelemetrySettings, get_telemetry_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def init_telemetry(
    service_name: str,
    db_engine: AsyncEngine | None = None,
    settings: TelemetrySettings | None = None,
    app: FastAPI | None = None,
) -> None:
    """
    OTel TracerProvider, MeterProvider를 초기화하고
    FastAPI / SQLAlchemy / httpx 자동 계측을 등록합니다.

    Args:
        service_name:   서비스 식별자 (예: "order-service")
                        grafana에서 서비스를 구분하는 기준이 됩니다.
        db_engine:      SQLAlchemy async engine (선택)
                        전달하면 DB 쿼리도 자동으로 Span으로 기록됩니다.
        settings:       TelemetrySettings 인스턴스 (없으면 환경변수에서 자동 로딩)
    """
    if settings is None:
        settings = get_telemetry_settings()

    if not settings.otel_enabled:
        return

    # 1. Resource 정의
    # 이 텔레메트리 데이터가 어느 서비스에서 왔는가 를 표시하는 메타데이터
    # Grafana에서 서비스별로 필터링할 때 이 값을 사용
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": settings.service_version,
        }
    )

    # 2. TracerProvider 설정 (분산 트레이싱)
    # Span 데이터를 OTel Collector로 전송
    # BatchSpanProcessor: Span을 즉시 보내지 않고 모아서 배치 전송
    # -> 네트워크 오버헤드를 줄이기 위한 표준 방식
    trace_provider = TracerProvider(resource=resource)
    otlp_span_exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        insecure=settings.otel_exporter_otlp_insecure,
    )
    trace_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    # 전역 TracerProvider로 등록
    # -> 이후 어디서든 trace.get_tracer()로 접근 가능
    trace.set_tracer_provider(trace_provider)

    # 3. MeterProvider 설정 (메트릭)
    # Counter, Histogram 등 메트릭을 OTel Collector로 전송
    # PeriodicExportingMetricReader: 정해진 시간마다 메트릭을 수집해서 전송
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=settings.otel_exporter_otlp_insecure,
        ),
        export_interval_millis=60000,  # 60초마다 전송
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # LoggerProvider 추가 (로그 → OTLP → Collector → Loki)
    # BatchLogRecordProcessor: Span과 동일하게 배치 전송으로 오버헤드 최소화
    logger_provider = LoggerProvider(resource=resource)
    otlp_log_exporter = OTLPLogExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
        insecure=settings.otel_exporter_otlp_insecure,
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))
    set_logger_provider(logger_provider)

    # Python 기본 logging -> OTel LogRecord로 브릿지
    # structlog에서 내보낸 로그가 trace_id와 함께 Loki로 전송됩니다.
    logging.basicConfig(level=logging.INFO)

    # httpx 에서는 warning 레벨 이상만 로깅
    # -> INFO 등의 로그는 middleware를 통해 로그를 남기는 중이므로 노이즈를 줄임
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # stdlib logging → OTel 브릿지 연결
    # LoggingInstrumentor가 Python logging.Handler를 심어서
    # logging.getLogger(...).info(...) 호출이 자동으로 OTLP로 전달됨
    LoggingInstrumentor().instrument(set_logging_format=False)

    # 4. 자동 계측 (Auto-instrumentation) 등록
    # 라이브러리 코드를 수정하지 않고도 Span이 자동 생성

    # FastAPI: 모든 HTTP 요청/응답에 자동으로 Span 생성
    if app is not None:
        FastAPIInstrumentor().instrument_app(app)

    # httpx: 다른 서비스로 보내는 HTTP 요청에 자동으로 Span 생성
    # + W3C TracContext 헤더(traceparent)를 자동으로 주입
    # -> 서비스 간 트레이스가 끊어지지 않고 연결되는 핵심 설정
    HTTPXClientInstrumentor().instrument()

    # SQLAlchemy: DB 쿼리마다 자동으로 Span 생성
    # db_engine이 없으면 건너뛰기 (api-gateway는 DB 없음)
    if db_engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=db_engine.sync_engine)

    logging.getLogger(__name__).info(
        f"[Telemetry] {service_name} OTel 초기화 완료"
        f"(endpoint: {settings.otel_exporter_otlp_endpoint})"
    )
