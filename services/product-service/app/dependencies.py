"""
product-service common FastAPI dependencies.

Authorization and internal-service checks live here so routes stay focused on
HTTP contracts and product behavior, matching order/payment-service structure.
"""

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_admin(x_user_role: str = Header(default="")) -> None:
    """
    Validate the X-User-Role header injected by api-gateway.

    product-service does not verify JWTs directly. It trusts gateway-verified
    headers inside the private service boundary; production deployments must
    still protect direct service access with network policy or mTLS.
    """
    if x_user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )


def verify_internal_service(
    x_internal_token: str = Header(default=""),
) -> None:
    """
    Protect internal product endpoints called by order-service.

    hmac.compare_digest keeps token comparison constant-time enough for this
    shared-secret boundary and preserves the existing security behavior.
    """
    settings = get_settings()
    if not settings.internal_service_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="내부 서비스 토큰이 설정되지 않았습니다.",
        )
    if not hmac.compare_digest(x_internal_token, settings.internal_service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="내부 서비스 인증에 실패했습니다.",
        )
