FROM python:3.12-slim-trixie AS builder

WORKDIR /build

# api-gateway는 DB 없음 → libpq 불필요, httpx만 필요
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements/ /build/requirements/

COPY shared/telemetry/requirements.txt /build/shared/telemetry/requirements.txt
RUN pip install --no-cache-dir -r /build/shared/telemetry/requirements.txt

COPY services/api-gateway/requirements.txt /build/services/api-gateway/requirements.txt
RUN pip install --no-cache-dir -r /build/services/api-gateway/requirements.txt

# ─────────────────────────────────────────────────────────
FROM python:3.12-slim-trixie AS runtime

WORKDIR /app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app

COPY shared/ /app/shared/
COPY services/api-gateway/app /app/app

RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
