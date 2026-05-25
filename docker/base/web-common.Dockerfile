# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-trixie AS builder

WORKDIR /build

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements/ /build/requirements/
COPY shared/telemetry/requirements.txt /build/shared/telemetry/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /build/requirements/web-common.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /build/shared/telemetry/requirements.txt

FROM python:3.12-slim-trixie AS runtime

WORKDIR /app

COPY --from=builder /app/venv /app/venv

RUN useradd -r -u 10001 -s /bin/false appuser

ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app
