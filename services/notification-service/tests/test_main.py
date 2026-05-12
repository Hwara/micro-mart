from app.main import _sanitize_nats_url


def test_sanitize_nats_url_removes_userinfo():
    """NATS URLs with credentials do not expose userinfo in logs."""
    sanitized = _sanitize_nats_url("nats://user:pass@nats:4222")

    assert sanitized == "nats://nats:4222"
    assert "user" not in sanitized
    assert "pass" not in sanitized


def test_sanitize_nats_url_keeps_url_without_userinfo():
    """NATS URLs without credentials are unchanged."""
    assert _sanitize_nats_url("nats://nats:4222") == "nats://nats:4222"
