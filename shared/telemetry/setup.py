"""
OpenTelemetry 초기화 모듈

모든 마이크로서비스가 이 모듈을 통해 OTel을 초기화합니다.
한 번 호출하면 FastAPI, SQLAlchemy, httpx의 계측이 자동으로 시작됩니다.
"""

import logging

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic_settings import BaseSettings


class TelemetrySettings(BaseSettings):
    """
    환경변수로 OTel 설정을 주입받습니다.
    docker-compose나 k8s ConfigMap에서 값을 넣어줍니다.
    """

    # OTel Collector 주소 (기본값: 로컬 개발용)
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # OTel TLS 적용 여부 (기본값: 로컬 개발용)
    otel_exporter_otlp_insecure: bool = True

    # 로그 출력 포맷: "json" (운영) | "pretty" (로컬 개발)
    log_format: str = "pretty"

    # 서비스 버전 (Docker 빌드 시 주입)
    service_version: str = "0.1.0"

    class Config:
        env_file = ".env"
        extra = "ignore"  # 정의되지 않은 환경변수는 무시


def init_telemetry(
    service_name: str,
    db_engine=None,
    settings: TelemetrySettings | None = None,
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
        settings = TelemetrySettings()

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

    # 4. 자동 계측 (Auto-instrumentation) 등록
    # 라이브러리 코드를 수정하지 않고도 Span이 자동 생성

    # FastAPI: 모든 HTTP 요청/응답에 자동으로 Span 생성
    FastAPIInstrumentor().instrument()

    # httpx: 다른 서비스로 보내는 HTTP 요청에 자동으로 Span 생성
    # + W3C TracContext 헤더(traceparent)를 자동으로 주입
    # -> 서비스 간 트레이스가 끊어지지 않고 연결되는 핵심 설정
    HTTPXClientInstrumentor().instrument()

    # SQLAlchemy: DB 쿼리마다 자동으로 Span 생성
    # db_engine이 없으면 건너뛰기 (api-gateway는 DB 없음)
    if db_engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=db_engine.sync_engine)

    # Python 기본 logging -> OTel LogRecord로 브릿지
    # structlog에서 내보낸 로그가 trace_id와 함께 Loki로 전송됩니다.
    logging.basicConfig(level=logging.INFO)

    logging.getLogger(__name__).info(
        f"[Telemetry] {service_name} OTel 초기화 완료"
        f"(endpoint: {settings.otel_exporter_otlp_endpoint})"
    )
