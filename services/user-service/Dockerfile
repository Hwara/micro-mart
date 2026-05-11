# ── Stage 1: builder ──────────────────────────────────────
# 의존성 설치만 수행. 이 레이어는 requirements.txt가 변경될 때만 재빌드됩니다.
FROM python:3.12-slim-trixie AS builder

WORKDIR /build

# 시스템 의존성: asyncpg(C 확장), bcrypt(cryptography) 빌드에 필요
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# venv를 명시적으로 생성해서 런타임 스테이지에 통째로 복사
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# 공통 버전 constraints를 먼저 복사해 모든 설치가 같은 버전 기준을 사용하게 합니다.
COPY requirements/ /build/requirements/

# shared/telemetry를 먼저 설치 (서비스 requirements보다 먼저 캐시)
COPY shared/telemetry/requirements.txt /build/shared/telemetry/requirements.txt
RUN pip install --no-cache-dir -r /build/shared/telemetry/requirements.txt

# 서비스 의존성 설치
COPY services/user-service/requirements.txt /build/services/user-service/requirements.txt
RUN pip install --no-cache-dir -r /build/services/user-service/requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────
FROM python:3.12-slim-trixie AS runtime

# 런타임에 필요한 최소 시스템 라이브러리만 포함
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# builder에서 설치 완료된 venv만 복사 (소스 불포함)
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app

# shared 패키지 소스 복사 (editable install이 참조)
COPY shared/ /app/shared/

# 서비스 소스 복사
COPY services/user-service/app /app/app

# non-root 유저: 컨테이너 탈출 시 호스트 권한 상승 방지
RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# uvicorn: --no-access-log는 structlog RequestLoggingMiddleware가 담당하므로 중복 방지
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
