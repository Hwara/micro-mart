"""
Rate Limiting 미들웨어

SlowAPI(slowapi)를 사용한 IP 기반 속도 제한.
인메모리 저장소 사용 → 단일 인스턴스 환경에 적합.
멀티 레플리카 환경에서는 Redis 백엔드로 교체 필요.

현재 설정: 분당 IP별 max 60 요청 (환경변수로 조정 가능).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import get_settings


def get_rate_limit_string() -> str:
    """환경변수 기반 Rate Limit 문자열 생성. 예: '60/minute'"""
    settings = get_settings()
    return f"{settings.rate_limit_per_minute}/minute"


# 클라이언트 IP 기준 제한 — X-Forwarded-For 헤더도 자동 처리
limiter = Limiter(key_func=get_remote_address)
