import os

import pytest

_TEST_ENV = {
    "OTEL_ENABLED": "false",
    "NATS_URL": "nats://mock-nats:4222",
    "NATS_SUBJECT_ORDER_COMPLETED": "order.completed",
    "NOTIFICATION_SEND_DELAY_MS": "0",
    "NOTIFICATION_FAILURE_RATE": "0.0",
}
_ORIGINAL_ENV = {key: os.environ.get(key) for key in _TEST_ENV}

for key, value in _TEST_ENV.items():
    os.environ[key] = value


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    """Reset notification-service settings around each test."""
    from app.config import get_settings

    get_settings.cache_clear()
    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def restore_import_time_env():
    """Restore env vars that tests set before importing app modules."""
    yield
    for key, original in _ORIGINAL_ENV.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
