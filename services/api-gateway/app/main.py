"""
api-gateway FastAPI 애플리케이션 진입점

DB 없음, Redis 없음 — stateless 서비스.
lifespan에서 JWKS 캐시를 미리 워밍업해두어
첫 번째 요청의 레이턴시 스파이크를 방지한다.

미들웨어 실행 순서 (아래서 위로, 나중에 add_middleware한 것이 먼저 실행):
  add_middleware 순서:     실제 실행 순서:
  1. RequestLoggingMiddleware  → ④ 가장 바깥 (요청 in / 응답 out 모두 기록)
  2. MetricsMiddleware         → ③ 레이턴시 측정 (로깅 안쪽)
  3. SlowAPIMiddleware         → ② Rate Limit 체크
  4. AuthMiddleware            → ① JWT 검증 (가장 먼저, Rate Limit 이후)

왜 Auth가 Rate Limit 이후인가:
  Rate Limit을 먼저 차단해야 JWT 검증 연산 자체의 낭비를 막을 수 있다.
  하지만 레이턴시/로깅은 인증 실패 포함 모든 요청을 측정해야 하므로 바깥에 위치.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.append(BASE_DIR)

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.datastructures import MutableHeaders  # Starlette 공식 헤더 변조 API
from starlette.middleware.base import BaseHTTPMiddleware

from shared.telemetry import RequestLoggingMiddleware, init_logging, init_telemetry

from .config import get_settings
from .middleware.auth import is_public_path, jwks_cache, verify_jwt
from .middleware.metrics import (
    gateway_auth_counter,
    gateway_auth_failure_counter,
    gateway_rate_limit_counter,
    gateway_request_duration,
    gateway_requests_counter,
)
from .middleware.rate_limit import limiter
from .router import router

logger = structlog.get_logger(__name__)


def _classify_path(path: str) -> str:
    """
    경로를 그룹 레이블로 변환.

    카디널리티 폭발 방지: /products/12345 → /products/{id}
    Prometheus 레이블에 실제 ID가 들어가면 시계열이 무한히 증가함.
    """
    if path.startswith("/auth"):
        return "/auth"
    if path == "/products" or path.startswith("/products/"):
        # /products/{id}/deduct-stock 등도 /products/{id}로 그루핑
        parts = path.split("/")
        if len(parts) > 2 and parts[2]:
            return (
                "/products/{id}" if len(parts) == 3 else f"/products/{{id}}/{'/'.join(parts[3:])}"
            )
        return "/products"
    if path.startswith("/orders"):
        parts = path.split("/")
        if len(parts) > 2 and parts[2]:
            return "/orders/{id}"
        return "/orders"
    if path == "/health":
        return "/health"
    return "/unknown"


def _classify_auth_failure(error_msg: str) -> str:
    """
    verify_jwt()가 raise한 ValueError 메시지에서 실패 유형 분류.

    메시지 형식: "expired:...", "invalid:...", "jwks_error:..."
    """
    if error_msg.startswith("expired:"):
        return "expired"
    if error_msg.startswith("jwks_error:"):
        return "jwks_error"
    return "invalid"


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    요청 레이턴시 + 상태 코드별 카운터 측정 미들웨어.

    모든 요청(인증 실패 포함)을 측정하므로 Auth 미들웨어 바깥에 위치.
    레이턴시는 미들웨어 진입~응답 반환 시점까지 측정 (프록시 왕복 포함).
    """

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        path_group = _classify_path(request.url.path)
        labels = {
            "method": request.method,
            "path_group": path_group,
            "status_code": str(response.status_code),
        }

        gateway_requests_counter.add(1, labels)
        gateway_request_duration.record(
            duration_ms, {"method": request.method, "path_group": path_group}
        )

        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT 검증 미들웨어.

    PUBLIC_PATHS는 검증 없이 통과 (auth_result=no_token으로 기록하지 않음).
    나머지 경로:
      - 토큰 없음 → 401, auth_result=no_token
      - 토큰 검증 실패 → 401, auth_result=failure + 실패 유형 상세 카운터
      - 검증 성공 → X-User-ID, X-User-Role 헤더 주입, auth_result=success
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        if is_public_path(method, path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # 토큰 자체가 없는 경우
            gateway_auth_counter.add(1, {"result": "no_token"})
            return JSONResponse(
                status_code=401,
                content={"detail": "인증 토큰이 필요합니다."},
            )

        token = auth_header[len("Bearer ") :]

        try:
            payload = await verify_jwt(token)
        except ValueError as e:
            error_msg = str(e)
            reason = _classify_auth_failure(error_msg)

            # 인증 실패 집계 (총량 + 유형별 상세)
            gateway_auth_counter.add(1, {"result": "failure"})
            gateway_auth_failure_counter.add(1, {"reason": reason})

            logger.warning(
                "JWT 검증 실패",
                error=error_msg,
                reason=reason,
                path=path,
                # 토큰 원문은 절대 로그에 남기지 않음 (보안 규칙)
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "인증에 실패했습니다.", "code": reason.upper()},
            )

        # 검증 성공
        gateway_auth_counter.add(1, {"result": "success"})

        user_id = str(payload.get("sub", ""))
        user_role = str(payload.get("role", "customer"))

        mutable_headers = MutableHeaders(scope=request.scope)
        mutable_headers.append("x-user-id", user_id)
        mutable_headers.append("x-user-role", user_role)

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 JWKS 캐시 워밍업."""
    settings = get_settings()
    init_logging(service_name=settings.service_name, log_format=settings.log_format)
    init_telemetry(service_name=settings.service_name)  # DB 없으므로 db_engine=None

    try:
        await jwks_cache._refresh()
        logger.info("JWKS 캐시 워밍업 완료")
    except Exception as e:
        logger.warning("JWKS 워밍업 실패 — 첫 요청 시 재시도됨", error=str(e))

    logger.info("api-gateway 시작 완료", version=settings.service_version)
    yield
    logger.info("api-gateway 종료")


def _create_app() -> FastAPI:
    """
    FastAPI 앱 팩토리.

    모듈 레벨 get_settings() 호출을 피하기 위해 함수로 감쌈.
    테스트 환경에서 환경변수 설정 전 임포트 시 잘못된 값이 캐싱되는 문제 방지.
    """
    s = get_settings()
    _app = FastAPI(
        title="MicroMart API Gateway",
        version=s.service_version,
        lifespan=lifespan,
        docs_url="/docs" if s.debug else None,
    )
    _app.state.limiter = limiter
    return _app


app = _create_app()

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Rate Limit 초과 카운터 기록
    gateway_rate_limit_counter.add(
        1,
        {"path_group": _classify_path(request.url.path)},
    )
    logger.warning(
        "Rate Limit 초과",
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."},
    )


# 미들웨어 등록 — add_middleware의 역순으로 실행됨
# 실행 순서: ① AuthMiddleware → ② SlowAPIMiddleware
#           → ③ MetricsMiddleware → ④ RequestLoggingMiddleware
app.add_middleware(RequestLoggingMiddleware)  # ④ 가장 바깥: 요청/응답 구조화 로그
app.add_middleware(MetricsMiddleware)  # ③ 레이턴시 측정 (인증 실패도 포함)
app.add_middleware(SlowAPIMiddleware)  # ② Rate Limit
app.add_middleware(AuthMiddleware)  # ① JWT 검증 (가장 먼저 실행)


# 구체적 경로(health)를 catch-all 라우터보다 반드시 먼저 등록
@app.get("/health")
async def health_check():
    """헬스체크 — k8s liveness probe용, 인증 불필요"""
    return {
        "status": "ok",
        "service": get_settings().service_name,
        "jwks_cached_keys": jwks_cache.key_count,
    }


# catch-all 라우터는 항상 마지막에 등록
app.include_router(router)
