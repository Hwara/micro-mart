from pathlib import Path

from alembic.config import Config

SERVICE_DIR = Path(__file__).resolve().parents[1]


def test_order_service_has_service_scoped_alembic_config() -> None:
    """order-service should own its Alembic history independently."""
    config_path = SERVICE_DIR / "alembic.ini"
    script_location = SERVICE_DIR / "alembic"

    config = Config(str(config_path))

    assert config_path.exists()
    assert Path(config.get_main_option("script_location")) == script_location
    assert script_location.joinpath("env.py").exists()
    assert script_location.joinpath("versions").is_dir()


def test_initial_revision_documents_order_tables() -> None:
    """The first migration should create and downgrade orders and order_items."""
    versions_dir = SERVICE_DIR / "alembic" / "versions"
    revision_files = list(versions_dir.glob("*.py"))

    assert len(revision_files) == 1

    revision_text = revision_files[0].read_text(encoding="utf-8")

    assert "create_order_tables" in revision_files[0].name
    assert '"orders"' in revision_text
    assert '"order_items"' in revision_text
    assert 'sa.ForeignKeyConstraint(["order_id"], ["orders.id"])' in revision_text
    assert (
        'op.create_index("ix_orders_user_id", "orders", ["user_id"], unique=False)' in revision_text
    )
    assert (
        'op.create_index("ix_order_items_order_id", "order_items", ["order_id"], unique=False)'
        in revision_text
    )
    assert 'op.drop_table("orders")' in revision_text
