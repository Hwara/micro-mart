FROM python:3.12-slim-trixie AS builder

WORKDIR /build

# nats-py는 순수 Python이지만 asyncpg는 C 확장 필요
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements/ /build/requirements/

COPY shared/telemetry/requirements.txt /build/shared/telemetry/requirements.txt
RUN pip install --no-cache-dir -r /build/shared/telemetry/requirements.txt

COPY services/order-service/requirements.txt /build/services/order-service/requirements.txt
RUN pip install --no-cache-dir -r /build/services/order-service/requirements.txt

# ─────────────────────────────────────────────────────────
FROM python:3.12-slim-trixie AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app

COPY shared/ /app/shared/
COPY services/order-service/app /app/app

RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
