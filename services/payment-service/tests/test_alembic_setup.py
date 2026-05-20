from pathlib import Path

from alembic.config import Config

SERVICE_DIR = Path(__file__).resolve().parents[1]


def test_payment_service_has_service_scoped_alembic_config() -> None:
    """payment-service should own its Alembic history independently."""
    config_path = SERVICE_DIR / "alembic.ini"
    script_location = SERVICE_DIR / "alembic"

    config = Config(str(config_path))

    assert config_path.exists()
    assert Path(config.get_main_option("script_location")) == script_location
    assert script_location.joinpath("env.py").exists()
    assert script_location.joinpath("versions").is_dir()


def test_initial_revision_documents_payment_tables() -> None:
    """The first migration should create and downgrade payments and refunds."""
    versions_dir = SERVICE_DIR / "alembic" / "versions"
    revision_files = list(versions_dir.glob("*.py"))

    assert len(revision_files) == 1

    revision_text = revision_files[0].read_text(encoding="utf-8")

    assert "create_payment_tables" in revision_files[0].name
    assert '"payments"' in revision_text
    assert '"refunds"' in revision_text
    assert 'sa.ForeignKeyConstraint(["payment_id"], ["payments.id"])' in revision_text
    assert (
        'op.create_index("ix_payments_order_id", "payments", ["order_id"], unique=True)'
        in revision_text
    )
    assert (
        'op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"], unique=False)'
        in revision_text
    )
    assert 'op.drop_table("payments")' in revision_text
