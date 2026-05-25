"""Regression checks for optional database telemetry dependencies."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


def test_sqlalchemy_instrumentation_is_not_imported_at_module_load() -> None:
    """DB-free services must import shared.telemetry without SQLAlchemy packages."""
    setup_path = Path(__file__).with_name("setup.py")
    module = ast.parse(setup_path.read_text(encoding="utf-8"))

    forbidden_modules = {
        "opentelemetry.instrumentation.sqlalchemy",
        "sqlalchemy.ext.asyncio",
    }
    forbidden_members = {
        "opentelemetry.instrumentation": {"sqlalchemy"},
        "sqlalchemy.ext": {"asyncio"},
    }

    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_modules
            assert not (
                node.module in forbidden_members
                and any(alias.name in forbidden_members[node.module] for alias in node.names)
            )

        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules


def test_shared_telemetry_setup_imports_without_db_dependencies() -> None:
    """Importing telemetry setup must not require SQLAlchemy runtime packages."""
    importlib.import_module("shared.telemetry.setup")
