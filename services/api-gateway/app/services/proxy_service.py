import httpx
import structlog
from fastapi import Request, Response
from opentelemetry import propagate

from ..config import get_settings

logger = structlog.get_logger(__name__)

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
        "host",
        "content-length",
    }
)
_RESPONSE_HEADER_EXCLUDES = _HOP_BY_HOP_HEADERS | {"content-encoding"}


def get_target_url(path: str) -> str | None:
    """
    요청 경로를 보고 라우팅할 하위 서비스 URL을 결정한다.

    정확한 prefix 경계(`/auth` 또는 `/auth/`)를 검사해 `/authz`,
    `/products-old` 같은 유사 경로의 오라우팅을 방지한다.
    """
    settings = get_settings()

    if path in {"/health"}:
        return None
    if path == "/auth" or path.startswith("/auth/"):
        return settings.user_service_url
    if path == "/products" or path.startswith("/products/"):
        return settings.product_service_url
    if path == "/orders" or path.startswith("/orders/"):
        return settings.order_service_url
    return None


async def proxy_request(request: Request, target_url: str) -> Response:
    """
    httpx로 하위 서비스에 요청을 프록시하고 응답을 그대로 반환한다.

    W3C TraceContext 헤더를 현재 span에서 주입해 하위 서비스 span이 같은
    trace_id를 이어받도록 한다.
    """
    settings = get_settings()
    headers = {}
    # request.headers may be cached before AuthMiddleware mutates scope headers.
    for raw_key, raw_value in request.scope["headers"]:
        key = raw_key.decode("latin-1")
        if key.lower() not in _HOP_BY_HOP_HEADERS:
            headers[key] = raw_value.decode("latin-1")
    propagate.inject(headers)

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

    resp_headers: list[tuple[str, str]] = [
        (k, v)
        for k, v in proxy_resp.headers.multi_items()
        if k.lower() not in _RESPONSE_HEADER_EXCLUDES
    ]

    resp = Response(
        content=proxy_resp.content,
        status_code=proxy_resp.status_code,
    )

    for k, v in resp_headers:
        resp.headers.append(k, v)

    return resp
