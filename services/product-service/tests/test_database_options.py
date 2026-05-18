from app.database import _engine_options


def test_engine_options_use_configured_pool_values_for_postgresql() -> None:
    """PostgreSQL engine options should use DB pool settings from config."""
    options = _engine_options(
        "postgresql+asyncpg://user:pass@localhost:5432/productdb",
        debug=False,
        pool_size=5,
        max_overflow=15,
    )

    assert options["pool_size"] == 5
    assert options["max_overflow"] == 15


def test_engine_options_skip_pool_values_for_sqlite() -> None:
    """SQLite test engines should not receive unsupported pool options."""
    options = _engine_options(
        "sqlite+aiosqlite:///:memory:",
        debug=False,
        pool_size=5,
        max_overflow=15,
    )

    assert "pool_size" not in options
    assert "max_overflow" not in options
