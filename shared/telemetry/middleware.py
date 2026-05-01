"""
FastAPI 요청/응답 로깅 미들웨어

각 HTTP 요청이 들어오고 나갈 때 구조화된 로그를 기록
trace_id가 이미 로그에 포함되어 있으므로 Grafana에서 특정 요청의 전체 흐름을 추적할 수 있습니다.

기록 내용:
- 요청: method, path, client_ip
- 응답: status_code, 처리 시간(ms)
- 에러: 4xx/5xx 상태 코드에서 경로/에러 레벨로 기록
"""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Starlette BaseHTTPMiddleware를 상속
    FastAPI는 내부적으로 Starlette 위에 구축되어 있어
    Starlette 미들웨어를 그대로 사용할 수 있습니다.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        # 요청 로그
        logger.info(
            "요청 수신",
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )

        # 다음 미들웨어 또는 라우터로 요청 전달
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "요청 실패",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
            )
            raise

        # 처리 시간 계산 (밀리초)
        duration_ms = (time.perf_counter() - start_time) * 1000

        # 상태 코드에 따라 로그 레벨 분기
        # 5xx: 서버 에러 -> error
        # 4xx: 클라이언트 에러 -> warning
        # 2xx/3xx 정상 -> info
        log_level = "info"
        if response.status_code >= 500:
            log_level = "error"
        elif response.status_code >= 400:
            log_level = "warning"

        getattr(logger, log_level)(
            "요청 완료",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        return response
