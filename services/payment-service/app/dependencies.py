"""
payment-service 공통 의존성

내부 서비스 토큰 검증 로직을 여기서 중앙 관리.
"""

import hmac

from fastapi import Header, HTTPException, status
from pydantic import ValidationError

from .config import get_settings


def verify_internal_service(
    x_internal_token: str = Header(default=""),
) -> None:
    """
    내부 서비스 전용 엔드포인트 보호 (order-service → payment-service).

    product-service와 동일한 패턴 사용.
    hmac.compare_digest: 타이밍 공격(timing attack) 방지를 위한 상수 시간 비교.
    """
    try:
        settings = get_settings()  # ← 함수 내부에서 호출 (lru_cache라 비용 없음)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="내부 서비스 토큰이 설정되지 않았습니다.",
        ) from e

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
