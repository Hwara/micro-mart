"""
notification-service FastAPI 애플리케이션 진입점.

DB/Redis 없는 stateless 서비스로 /health만 제공한다.
lifespan에서 NATS core subscribe를 등록하며 연결 실패는 앱 기동 실패로 만들지 않는다.
"""

from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

import structlog
from fastapi import FastAPI

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .nats_client import clear_nats_client, get_nats_client, set_nats_client
from .services.notification_service import handle_order_completed_message

logger = structlog.get_logger(__name__)


def _sanitize_nats_url(url: str) -> str:
    """로그에 남길 NATS URL에서 userinfo를 제거한다."""
    parsed = urlsplit(url)
    if "@" not in parsed.netloc:
        return url

    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


async def _handle_nats_message(msg) -> None:
    """NATS callback에서 raw payload만 서비스 계층으로 넘긴다."""
    await handle_order_completed_message(msg.data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 NATS 연결과 구독을 관리한다."""
    settings = get_settings()
    sanitized_nats_url = _sanitize_nats_url(settings.nats_url)

    try:
        import nats as nats_lib

        nc = await nats_lib.connect(
            settings.nats_url,
            connect_timeout=settings.nats_connect_timeout_seconds,
        )
        set_nats_client(nc)
        await nc.subscribe(settings.nats_subject_order_completed, cb=_handle_nats_message)
        logger.info(
            "nats_subscription_started",
            nats_url=sanitized_nats_url,
            subject=settings.nats_subject_order_completed,
        )
    except Exception as exc:
        set_nats_client(None)
        logger.warning(
            "nats_connection_failed",
            nats_url=sanitized_nats_url,
            subject=settings.nats_subject_order_completed,
            error=str(exc),
        )

    logger.info("notification-service 시작 완료", version=settings.service_version)
    yield

    logger.info("notification-service 종료 시작")
    nc = get_nats_client()
    if nc and not nc.is_closed:
        try:
            await nc.close()
        except Exception as exc:
            logger.warning("nats_close_failed", error=str(exc))
    clear_nats_client()
    logger.info("notification-service 종료 완료")


settings = get_settings()

app = FastAPI(
    title="MicroMart Notification Service",
    version=settings.service_version,
    lifespan=lifespan,
)

init_telemetry(service_name=settings.service_name, app=app)
init_logging(service_name=settings.service_name, log_format=settings.log_format)

app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트 - k8s liveness probe용."""
    nc = get_nats_client()
    return {
        "status": "ok",
        "service": settings.service_name,
        "nats_connected": nc is not None and not nc.is_closed,
        "subject": settings.nats_subject_order_completed,
    }
