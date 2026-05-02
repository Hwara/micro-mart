"""
product-service 환경변수 설정

pydantic-settings는 클래스 필드와 동일한 이름의 환경변수를 자동으로 읽음
예) DATABASE_URL 환경변수 -> database_url 필드에 자동 매핑
"""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 현재 파일(config.py)의 위치를 기준으로 절대 경로 계산
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_path, extra="ignore", env_file_encoding="utf-8")

    # 서비스 식별
    service_name: str = "product-service"
    service_version: str = "0.1.0"
    debug: bool = False

    # 내부 서비스 토큰
    internal_service_token: str

    # DB: infra.yaml의 productdb 연결
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/productdb"

    # Redis: user-service와 동일 인스턴스, 다른 키 네임스페이스로 격리
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_connect_timeout: float = 1.0
    redis_socket_timeout: float = 1.0

    # 캐시 TTL: 상품 데이터는 자주 변하지 않으므로 5분으로 설정
    # 너무 길면 수정 후 반영이 늦고, 너무 짧으면 캐시 효과가 없음
    product_cache_ttl: int = 300  # seconds

    # OTel — 반드시 otel_exporter_otlp_endpoint 이름 사용 (축약형 금지)
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    # log_format 기본값은 json (pretty는 로컬 개발 시 .env로 오버라이드)
    log_format: str = "json"

    # 페이지네이션 기본값
    default_page_size: int = 20
    max_page_size: int = 100


# lru_cache: Settings 객체를 한 번만 생성하고 재사용
# 환경변수를 매번 읽지 않아도 되므로 성능상 이점이 있음
@lru_cache
def get_settings() -> Settings:
    return Settings()
