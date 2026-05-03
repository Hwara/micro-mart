import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from app.config import get_settings

INTERNAL_TOKEN = "test-internal-token"


@pytest.fixture(autouse=True)
def setup_env():
    """
    모든 테스트 전: 환경변수 설정 + 캐시 초기화
    모든 테스트 후: 캐시 초기화 (다음 테스트가 깨끗한 Settings 받도록)

    순서가 중요:
    1. cache_clear() → 기존 캐시 제거
    2. setenv() → 새 환경변수 설정
    3. get_settings() → 새 환경변수로 인스턴스 생성 + 캐시
    """
    get_settings.cache_clear()
    os.environ["INTERNAL_SERVICE_TOKEN"] = INTERNAL_TOKEN
    yield
    get_settings.cache_clear()
