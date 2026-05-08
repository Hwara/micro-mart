"""
payment-service FastAPI 애플리케이션 진입점

product-service 패턴과 동일한 구조 유지.
Redis가 없으므로 close_db는 engine.dispose만 호출.
"""

import os
import sys

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(BASE_DIR)

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .database import close_db, engine, init_db
from .routes.payments import router as payments_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행되는 로직."""
    settings = get_settings()

    if settings.debug:
        await init_db()

    logger.info(
        "payment-service 시작 완료",
        version=settings.service_version,
        chaos_failure_rate=settings.chaos_failure_rate,
        chaos_latency_ms=settings.chaos_latency_ms,
        chaos_db_slowquery=settings.chaos_db_slowquery,
    )
    yield

    logger.info("payment-service 종료 시작")
    await close_db()
    logger.info("payment-service 종료 완료")


settings = get_settings()


app = FastAPI(
    title="MicroMart Payment Service",
    version=settings.service_version,
    lifespan=lifespan,
)

init_telemetry(service_name=settings.service_name, db_engine=engine, app=app)
init_logging(service_name=settings.service_name, log_format=settings.log_format)

app.add_middleware(RequestLoggingMiddleware)
app.include_router(payments_router)


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트 — k8s liveness probe용"""
    return {
        "status": "ok",
        "service": settings.service_name,
        # Chaos Mode 상태를 헬스체크에 포함해 운영 중 설정 확인 가능
        "chaos": {
            "failure_rate": settings.chaos_failure_rate,
            "latency_ms": settings.chaos_latency_ms,
            "db_slowquery": settings.chaos_db_slowquery,
        },
    }
