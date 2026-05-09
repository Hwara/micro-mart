import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from app.config import get_settings

INTERNAL_TOKEN = "test-internal-token"
_ORIGINAL_INTERNAL_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN")
_ORIGINAL_OTEL_ENABLED = os.environ.get("OTEL_ENABLED")

# config.py no longer reads .env files directly. Set the required token before
# test modules import app.main, which creates the FastAPI app at module import.
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", INTERNAL_TOKEN)
os.environ.setdefault("OTEL_ENABLED", "false")


@pytest.fixture(autouse=True)
def setup_env():
    """
    모든 테스트 전: 환경변수 설정 + 캐시 초기화
    모든 테스트 후: 캐시 초기화 (다음 테스트가 깨끗한 Settings 받도록)

    순서가 중요:
    1. cache_clear() → 기존 캐시 제거
    2. setenv() → 새 환경변수 설정
    3. get_settings() → 새 환경변수로 인스턴스 생성 + 캐시

    원래 값을 보관했다가 테스트 종료 후 정확히 복원.
    원래 값이 없었다면 키 자체를 삭제 (설정 안 된 상태로 복원).
    """
    get_settings.cache_clear()
    os.environ["INTERNAL_SERVICE_TOKEN"] = INTERNAL_TOKEN
    os.environ["OTEL_ENABLED"] = "false"
    yield
    get_settings.cache_clear()
    if _ORIGINAL_INTERNAL_TOKEN is None:
        os.environ.pop("INTERNAL_SERVICE_TOKEN", None)  # 원래 없었으면 삭제
    else:
        os.environ["INTERNAL_SERVICE_TOKEN"] = _ORIGINAL_INTERNAL_TOKEN  # 원래 값으로 복원
    if _ORIGINAL_OTEL_ENABLED is None:
        os.environ.pop("OTEL_ENABLED", None)
    else:
        os.environ["OTEL_ENABLED"] = _ORIGINAL_OTEL_ENABLED
