import pytest
from app.config import Settings, get_settings
from app.dependencies import require_admin, verify_internal_service
from fastapi import HTTPException
from pydantic import ValidationError


def test_require_admin_accepts_admin_role() -> None:
    """admin role header는 관리자 의존성을 통과하는지 확인한다."""
    assert require_admin(x_user_role="admin") is None


@pytest.mark.parametrize("role", ["customer", ""])
def test_require_admin_rejects_non_admin_roles(role: str) -> None:
    """admin이 아닌 role header는 403으로 차단되는지 확인한다."""
    with pytest.raises(HTTPException) as exc:
        require_admin(x_user_role=role)

    assert exc.value.status_code == 403


def test_verify_internal_service_accepts_matching_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """내부 서비스 토큰이 설정값과 일치하면 인증이 통과되는지 확인한다."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "expected")  # noqa: S106
    get_settings.cache_clear()

    assert verify_internal_service(x_internal_token="expected") is None


def test_verify_internal_service_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """내부 서비스 토큰이 다르면 401로 차단되는지 확인한다."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "expected")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        verify_internal_service(x_internal_token="wrong")

    assert exc.value.status_code == 401


def test_empty_internal_service_token_is_configuration_error() -> None:
    """비어 있는 내부 서비스 토큰 설정은 Settings 생성 단계에서 거부되는지 확인한다."""
    with pytest.raises(ValidationError):
        Settings(internal_service_token="")
