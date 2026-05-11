"""
order-service FastAPI 애플리케이션 진입점

NATS 커넥션은 nats_client.py 싱글턴으로 관리.
  - lifespan에서 connect/set → order_service에서 get → lifespan 종료 시 close/clear
  - 순환 import 방지 + 커넥션 재사용 두 가지 목표 동시 달성
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .database import close_db, engine, init_db
from .nats_client import clear_nats_client, get_nats_client, set_nats_client
from .routes.orders import router as orders_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행되는 로직."""
    settings = get_settings()

    if settings.debug:
        await init_db()

    # NATS 커넥션 초기화 — 실패해도 서비스 기동은 계속 (이벤트 발행 best-effort)
    try:
        import nats as nats_lib

        nc = await nats_lib.connect(
            settings.nats_url, connect_timeout=settings.nats_connect_timeout_seconds
        )
        set_nats_client(nc)
        logger.info("NATS 커넥션 연결 완료", nats_url=settings.nats_url)
    except Exception as e:
        set_nats_client(None)
        logger.warning("NATS 커넥션 실패 — 이벤트 발행 비활성화", error=str(e))

    logger.info("order-service 시작 완료", version=settings.service_version)
    yield

    # 종료 시 NATS 정리
    logger.info("order-service 종료 시작")
    nc = get_nats_client()
    if nc and not nc.is_closed:
        try:
            await nc.close()
        except Exception as e:
            logger.warning("NATS 종료 중 오류", error=str(e))
    clear_nats_client()

    await close_db()
    logger.info("order-service 종료 완료")


settings = get_settings()

app = FastAPI(
    title="MicroMart Order Service",
    version=settings.service_version,
    lifespan=lifespan,
)

init_telemetry(service_name=settings.service_name, db_engine=engine, app=app)
init_logging(service_name=settings.service_name, log_format=settings.log_format)

app.add_middleware(RequestLoggingMiddleware)
app.include_router(orders_router)


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트 — k8s liveness probe용"""
    nc = get_nats_client()
    return {
        "status": "ok",
        "service": settings.service_name,
        "nats_connected": nc is not None and not nc.is_closed,
    }
