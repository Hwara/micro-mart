"""
user-service 환경변수 설정

pydantic-settings는 클래스 필드와 동일한 이름의 환경변수를 자동으로 읽음
예) DATABASE_URL 환경변수 -> DATABASE_URL = database_url = 동일
"""

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 현재 파일(settings.py)의 위치를 기준으로 절대 경로 계산
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=env_path, extra="ignore", env_file_encoding="utf-8")

    # 서비스 기본 설정
    service_name: str = "user-service"
    service_version: str = "0.1.0"
    debug: bool = False

    # 데이터베이스
    database_url: str = "postgresql+asyncpg://micromart:micromart@localhost:5432/userdb"
    # SQLAlchemy 비동기 드라이버는 URL이 "postgresql+asyncpg://" 형식이어야 함

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    # /0 은 Redis DB 번호로 0~15 중 선택, 서비스별로 다른 번호 사용을 권장

    # JWT 설정
    # ── 키 주입 방식 (둘 중 하나만 설정하면 됨) ──
    jwt_private_key_file: str = ""  # 로컬 개발: 파일 경로
    jwt_public_key_file: str = ""
    jwt_private_key: str = ""  # k8s: 환경변수로 PEM 문자열 직접 주입
    jwt_public_key: str = ""

    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # OTel 설정
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_format: str = "pretty"

    @model_validator(mode="after")
    def load_jwt_keys(self) -> "Settings":
        """
        Settings 객체 생성 시 딱 한 번만 실행됩니다.
        파일 경로가 있으면 파일을 읽어 jwt_private_key/jwt_public_key에 덮어씁니다.
        """
        if self.jwt_private_key_file:
            with open(self.jwt_private_key_file) as f:
                self.jwt_private_key = f.read()

        if self.jwt_public_key_file:
            with open(self.jwt_public_key_file) as f:
                self.jwt_public_key = f.read()

        return self


# lru_cache: Settings 객체를 한 번만 생성하고 재사용
# 환경변수를 매번 읽지 않아도 되므로 성능상 이점이 있음
@lru_cache
def get_settings() -> Settings:
    return Settings()
