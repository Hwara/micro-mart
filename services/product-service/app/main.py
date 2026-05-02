# services/product-service/app/main.py

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .database import close_db, engine, init_db
from .routes.products import router as products_router

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 리소스 관리."""
    # 시작
    # OTel 초기화: shared/telemetry Phase 1 모듈 재사용
    init_logging(service_name=settings.service_name, log_format=settings.log_format)
    init_telemetry(service_name=settings.service_name, db_engine=engine)

    if settings.debug:
        await init_db()
    logger.info("product-service 시작 완료", version=settings.service_version)

    yield

    # 종료
    logger.info("product-service 종료 시작")
    await close_db()
    logger.info("product-service 종료 완료")


app = FastAPI(
    title="MicroMart Product Service",
    version=settings.service_version,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.include_router(products_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.service_name}
