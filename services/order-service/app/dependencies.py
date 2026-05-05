"""
order-service 공통 의존성

X-User-ID: api-gateway가 JWT 검증 후 주입하는 헤더.
  바디에서 user_id를 받지 않는 이유 → 외부 입력값을 신뢰하지 않는 원칙.
  gateway가 검증한 헤더만 신뢰.

X-User-Role: 관리자 전용 기능에서 역할 검증용.
"""

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def get_current_user_id(
    x_user_id: str = Header(default=""),
) -> int:
    """
    gateway가 주입한 X-User-ID 헤더에서 user_id 추출.

    빈 값이면 401 반환 — gateway를 우회한 직접 호출 방어.
    int 변환 실패는 gateway 버그이므로 400이 아닌 500 처리.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 정보가 없습니다.",
        )
    try:
        return int(x_user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 사용자 ID 형식입니다.",
        ) from e


def get_current_user_role(
    x_user_role: str = Header(default="customer"),
) -> str:
    """gateway가 주입한 X-User-Role 헤더에서 role 추출."""
    return x_user_role


def verify_internal_service(
    x_internal_token: str = Header(default=""),
) -> None:
    """
    내부 서비스 전용 엔드포인트 보호.
    payment-service 패턴과 동일 — hmac.compare_digest로 타이밍 공격 방지.
    """
    settings = get_settings()
    if not hmac.compare_digest(x_internal_token, settings.internal_service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="내부 서비스 인증에 실패했습니다.",
        )
