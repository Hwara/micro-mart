"""
user-service FastAPI 애플리케이션 진입점
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .database import close_db, engine, init_db
from .routes import auth as auth_router

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱 시작/종료 시 실행되는 로직

    lifespan은 FastAPI 0.93+에서 권장하는 방식입니다.
    이전에 사용하던 @app.on_event("startup")을 대체합니다.
    """
    # ── 시작 시 ──
    init_logging(service_name=settings.service_name, log_format=settings.log_format)
    init_telemetry(service_name=settings.service_name, db_engine=engine)

    # DB 테이블 자동 생성 (개발용, 운영에서는 Alembic 마이그레이션 사용)
    if settings.debug:
        await init_db()

    logger.info("user-service 시작 완료", version=settings.service_version)
    yield

    # ── 종료 시 ──
    logger.info("user-service 종료 시작")
    await close_db()
    logger.info("user-service 종료 완료")


app = FastAPI(
    title="MicroMart User Service",
    version=settings.service_version,
    lifespan=lifespan,
)

# 미들웨어 등록 (등록 순서의 역순으로 실행됨)
app.add_middleware(RequestLoggingMiddleware)

# 라우터 등록
app.include_router(auth_router.router)


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트 — k8s liveness probe용"""
    return {"status": "ok", "service": settings.service_name}
