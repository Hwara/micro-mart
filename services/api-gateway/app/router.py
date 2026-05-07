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

# RFC 7230 hop-by-hop 헤더 — 프록시가 제거해야 하는 헤더 목록
# 이 헤더들은 단일 전송 구간에만 적용되며 end-to-end로 전달하면 안 됨
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailers",
        "upgrade",
        "proxy-authenticate",
        "proxy-authorization",
        "host",  # 하위 서비스 호스트로 덮어써야 하므로 제거
        "content-length",  # httpx가 재계산
    }
)


# 경로 prefix → 서비스 URL 매핑
def _get_target_url(path: str) -> str | None:
    """
    요청 경로를 보고 라우팅할 하위 서비스 URL을 결정한다.

    startswith("/auth") 대신 "/auth" == path or startswith("/auth/") 패턴 사용.
    이유: /authz, /products-old 같은 유사 경로가 잘못 라우팅되는 버그 방지.
    """
    settings = get_settings()

    # gateway 자체 처리 경로 — 하위 서비스로 프록시하지 않음
    # /health는 app 레벨에서 직접 처리
    GATEWAY_OWN_PATHS = {"/health"}
    if path in GATEWAY_OWN_PATHS:
        return None  # 라우터에 닿으면 안 되지만, 혹시 닿아도 None 반환

    if path == "/auth" or path.startswith("/auth/"):
        return settings.user_service_url
    if path == "/products" or path.startswith("/products/"):
        return settings.product_service_url
    if path == "/orders" or path.startswith("/orders/"):
        return settings.order_service_url
    return None


async def _proxy_request(request: Request, target_url: str) -> Response:
    """
    httpx로 하위 서비스에 요청을 프록시한다.

    에러 처리:
      TimeoutException → 504 Gateway Timeout
      RequestError     → 503 Service Unavailable
      기타 예외        → 502 Bad Gateway
    """
    settings = get_settings()

    # hop-by-hop 헤더 및 proxy 헤더 제거 (소문자 비교)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}

    body = await request.body()
    url = f"{target_url}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            proxy_resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
    except httpx.TimeoutException as e:
        # 하위 서비스 응답 타임아웃 — order-service 패턴과 동일하게 504
        logger.warning(
            "하위 서비스 타임아웃",
            target_url=f"{target_url}{request.url.path}",
            has_query=bool(request.url.query),
            timeout=settings.http_timeout_seconds,
            error=str(e),
        )
        return Response(
            status_code=504,
            content='{"detail": "하위 서비스 응답 시간 초과", "code": "GATEWAY_TIMEOUT"}',
            media_type="application/json",
        )
    except httpx.RequestError as e:
        # 네트워크 오류, DNS 실패, 연결 거부 등 — 503
        logger.error(
            "하위 서비스 연결 실패",
            target_url=f"{target_url}{request.url.path}",
            has_query=bool(request.url.query),
            error=str(e),
        )
        return Response(
            status_code=503,
            content='{"detail": "하위 서비스를 사용할 수 없습니다", "code": "SERVICE_UNAVAILABLE"}',
            media_type="application/json",
        )

    # multi_items()로 중복 헤더(Set-Cookie 등) 모두 보존
    resp_headers: list[tuple[str, str]] = [
        (k, v) for k, v in proxy_resp.headers.multi_items() if k.lower() not in _HOP_BY_HOP_HEADERS
    ]

    resp = Response(
        content=proxy_resp.content,
        status_code=proxy_resp.status_code,
    )

    for k, v in resp_headers:
        resp.headers.append(k, v)

    return resp


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
