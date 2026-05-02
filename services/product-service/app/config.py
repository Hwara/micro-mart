import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 현재 파일(settings.py)의 위치를 기준으로 절대 경로 계산
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_path, extra="ignore", env_file_encoding="utf-8")

    # 서비스 식별
    service_name: str = "product-service"
    service_version: str = "0.1.0"
    debug: bool = False

    # 내부 서비스 토큰
    internal_service_token: str = "change-me-in-production"

    # DB: infra.yaml의 productdb 연결
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/productdb"

    # Redis: user-service와 동일 인스턴스, 다른 키 네임스페이스로 격리
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_connect_timeout: float = 1.0
    redis_socket_timeout: float = 1.0

    # 캐시 TTL: 상품 데이터는 자주 변하지 않으므로 5분으로 설정
    # 너무 길면 수정 후 반영이 늦고, 너무 짧으면 캐시 효과가 없음
    product_cache_ttl: int = 300  # seconds

    # 목록 캐시는 상세보다 짧게: 상품 추가/삭제 시 즉시 반영이 더 중요
    product_list_cache_ttl: int = 60  # seconds

    # OTel
    otlp_endpoint: str = "http://localhost:4317"
    log_format: str = "json"

    # 페이지네이션 기본값
    default_page_size: int = 20
    max_page_size: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
