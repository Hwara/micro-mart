# syntax=docker/dockerfile:1.7

FROM web_common_base AS runtime

COPY requirements/ /build/requirements/
COPY services/notification-service/requirements.txt /build/services/notification-service/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /build/services/notification-service/requirements.txt

COPY --chown=10001:10001 shared/ /app/shared/
COPY --chown=10001:10001 services/notification-service/app /app/app
USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
