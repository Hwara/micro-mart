import pytest
from app.config import Settings, get_settings
from app.dependencies import require_admin, verify_internal_service
from fastapi import HTTPException
from pydantic import ValidationError


def test_require_admin_accepts_admin_role() -> None:
    assert require_admin(x_user_role="admin") is None


@pytest.mark.parametrize("role", ["customer", ""])
def test_require_admin_rejects_non_admin_roles(role: str) -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin(x_user_role=role)

    assert exc.value.status_code == 403


def test_verify_internal_service_accepts_matching_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "expected")
    get_settings.cache_clear()

    assert verify_internal_service(x_internal_token="expected") is None


def test_verify_internal_service_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "expected")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        verify_internal_service(x_internal_token="wrong")

    assert exc.value.status_code == 401


def test_empty_internal_service_token_is_configuration_error() -> None:
    with pytest.raises(ValidationError):
        Settings(internal_service_token="")
