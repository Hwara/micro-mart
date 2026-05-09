FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY shared/telemetry/requirements.txt /build/shared-requirements.txt
RUN pip install --no-cache-dir -r /build/shared-requirements.txt

COPY services/product-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app

COPY shared/ /app/shared/
COPY services/product-service/app /app/app

RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
