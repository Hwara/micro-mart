# syntax=docker/dockerfile:1.7

FROM db_common_base AS runtime

COPY requirements/ /build/requirements/
COPY services/user-service/requirements.txt /build/services/user-service/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /build/services/user-service/requirements.txt

# shared 패키지 소스 복사 (editable install이 참조)
COPY --chown=10001:10001 shared/ /app/shared/

# 서비스 소스 복사
COPY --chown=10001:10001 services/user-service/app /app/app

# non-root 유저: 컨테이너 탈출 시 호스트 권한 상승 방지
USER 10001:10001

EXPOSE 8000

# uvicorn: --no-access-log는 structlog RequestLoggingMiddleware가 담당하므로 중복 방지
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
