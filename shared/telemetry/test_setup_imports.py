"""Regression checks for optional database telemetry dependencies."""

from __future__ import annotations

import ast
from pathlib import Path


def test_sqlalchemy_instrumentation_is_not_imported_at_module_load() -> None:
    """DB-free services must import shared.telemetry without SQLAlchemy packages."""
    setup_path = Path(__file__).with_name("setup.py")
    module = ast.parse(setup_path.read_text(encoding="utf-8"))

    forbidden_modules = {
        "opentelemetry.instrumentation.sqlalchemy",
        "sqlalchemy.ext.asyncio",
    }

    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_modules
