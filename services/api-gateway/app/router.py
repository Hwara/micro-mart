"""
api-gateway 라우팅 및 리버스 프록시

설계:
- 경로 prefix 기반으로 하위 서비스 URL을 결정한다.
- httpx.AsyncClient로 요청을 스트리밍 전달하고 응답을 그대로 반환한다.
- JWT 검증은 각 핸들러가 아닌 미들웨어(auth.py)에서 처리한다.
  라우터는 헤더가 이미 주입된 요청만 받는다.

경로 매핑:
  /auth/*       → user-service
  /products/*   → product-service
  /orders/*     → order-service
"""

import httpx
import structlog
from fastapi import APIRouter, Request, Response

from .config import get_settings
from .middleware.rate_limit import get_rate_limit_string, limiter

logger = structlog.get_logger(__name__)

router = APIRouter()


# 경로 prefix → 서비스 URL 매핑
def _get_target_url(path: str) -> str | None:
    """요청 경로를 보고 라우팅할 하위 서비스 URL을 결정한다."""
    settings = get_settings()

    # gateway 자체 처리 경로 — 하위 서비스로 프록시하지 않음
    # /health, /docs, /openapi.json은 app 레벨에서 직접 처리
    GATEWAY_OWN_PATHS = ("/health", "/docs", "/openapi.json")
    if path in GATEWAY_OWN_PATHS or path.startswith("/docs/"):
        return None  # 라우터에 닿으면 안 되지만, 혹시 닿아도 None 반환

    if path.startswith("/auth"):
        return settings.user_service_url
    if path.startswith("/products"):
        return settings.product_service_url
    if path.startswith("/orders"):
        return settings.order_service_url
    return None


async def _proxy_request(request: Request, target_url: str) -> Response:
    """
    httpx로 하위 서비스에 요청을 프록시한다.

    - 원본 헤더를 그대로 전달 (X-User-ID, X-User-Role 포함)
    - host 헤더는 제거 (하위 서비스의 host와 충돌 방지)
    - 응답 body를 스트리밍으로 반환 (대용량 응답 메모리 절약)
    """
    settings = get_settings()

    # host 헤더 제거 — 프록시 시 하위 서비스의 호스트가 덮어쓰여야 함
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")
    }

    body = await request.body()
    url = f"{target_url}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        proxy_resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )

    # 응답 헤더 중 transfer-encoding은 StreamingResponse와 충돌하므로 제거
    resp_headers = {
        k: v
        for k, v in proxy_resp.headers.items()
        if k.lower() not in ("transfer-encoding", "content-encoding")
    }

    return Response(
        content=proxy_resp.content,
        status_code=proxy_resp.status_code,
        headers=resp_headers,
        media_type=proxy_resp.headers.get("content-type"),
    )


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
@limiter.limit(get_rate_limit_string())  # Rate Limit 적용
async def gateway_proxy(request: Request, path: str) -> Response:
    """
    모든 요청을 받아 경로 기반으로 하위 서비스에 프록시.

    이 핸들러에 도달하기 전에 auth 미들웨어가 JWT 검증을 마치고
    X-User-ID, X-User-Role 헤더를 이미 추가한 상태.
    """
    full_path = f"/{path}"
    target_url = _get_target_url(full_path)

    if target_url is None:
        # /health 등 gateway 자체 경로는 app 레벨에서 처리됨
        # 여기 도달했다면 등록되지 않은 경로
        logger.warning("라우팅 대상 없음", path=full_path)
        return Response(
            content='{"detail": "존재하지 않는 경로입니다.", "code": "NOT_FOUND"}',
            status_code=404,
            media_type="application/json",
        )

    logger.info(
        "프록시 요청",
        method=request.method,
        path=full_path,
        target=target_url,
    )
    return await _proxy_request(request, target_url)
