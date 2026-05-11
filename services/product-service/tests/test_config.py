import pytest
from app.config import Settings
from pydantic import ValidationError


def test_internal_service_token_rejects_empty_string() -> None:
    """INTERNAL_SERVICE_TOKEN must fail at settings load time when empty."""
    with pytest.raises(ValidationError):
        Settings(internal_service_token="")


def test_internal_service_token_rejects_whitespace_only_string() -> None:
    """INTERNAL_SERVICE_TOKEN must reject whitespace-only values."""
    with pytest.raises(ValidationError):
        Settings(internal_service_token="   ")


def test_internal_service_token_accepts_non_empty_value() -> None:
    """A non-empty internal service token should load normally."""
    settings = Settings(internal_service_token="test-token")
    assert settings.internal_service_token == "test-token"
