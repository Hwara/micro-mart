"""
api-gateway 라우팅 및 리버스 프록시 HTTP 경계.

JWT 검증은 미들웨어에서 처리하고, 실제 proxy 실행은 services/proxy_service.py에 둔다.
"""

import structlog
from fastapi import APIRouter, Request, Response

from .middleware.rate_limit import get_rate_limit_string, limiter
from .services.proxy_service import get_target_url, proxy_request

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
@limiter.limit(get_rate_limit_string())
async def gateway_proxy(request: Request, path: str) -> Response:
    """
    모든 요청을 받아 경로 기반으로 하위 서비스에 프록시한다.

    등록되지 않은 경로는 gateway 라우터에서 기존 404 응답 구조를 유지한다.
    """
    full_path = f"/{path}"
    target_url = get_target_url(full_path)

    if target_url is None:
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
    return await proxy_request(request, target_url)
