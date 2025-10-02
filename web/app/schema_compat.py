"""Utilities to keep backward compatibility with older database schemas."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError, OperationalError
from flask import current_app

from . import db


@contextmanager
def _connection() -> Iterable[Connection]:
    """Return a connection bound to the current Flask-SQLAlchemy engine."""
    engine = db.engine
    with engine.begin() as conn:
        yield conn


def ensure_schema_compatibility() -> None:
    """Ensure columns introduced after the initial schema exist.

    The production database that ships with the appliance might predate the
    ``unique_item`` / ``unique_quantity`` fields as well as the
    ``event_stock.selected_quantity`` column.  When running against such a
    database we add the columns on the fly so that the application can start
    without requiring a manual Alembic migration.
    """

    with _connection() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if "stock_nodes" in tables:
            _ensure_stock_nodes_columns(conn, inspector)

        if "event_stock" in tables:
            _ensure_event_stock_columns(conn, inspector)


def _ensure_stock_nodes_columns(conn: Connection, inspector) -> None:
    columns = {col["name"] for col in inspector.get_columns("stock_nodes")}

    if "unique_item" not in columns:
        current_app.logger.info("Adding column stock_nodes.unique_item")
        _execute_ignore_duplicate(
            conn,
            "ALTER TABLE stock_nodes ADD COLUMN unique_item BOOLEAN NOT NULL DEFAULT FALSE",
        )

    if "unique_quantity" not in columns:
        current_app.logger.info("Adding column stock_nodes.unique_quantity")
        _execute_ignore_duplicate(
            conn,
            "ALTER TABLE stock_nodes ADD COLUMN unique_quantity INTEGER",
        )


def _ensure_event_stock_columns(conn: Connection, inspector) -> None:
    columns = {col["name"] for col in inspector.get_columns("event_stock")}

    if "selected_quantity" not in columns:
        current_app.logger.info("Adding column event_stock.selected_quantity")
        _execute_ignore_duplicate(
            conn,
            "ALTER TABLE event_stock ADD COLUMN selected_quantity INTEGER",
        )


def _execute_ignore_duplicate(conn: Connection, sql: str) -> None:
    try:
        conn.execute(text(sql))
    except ProgrammingError as exc:  # pragma: no cover - defensive
        if getattr(getattr(exc, "orig", None), "pgcode", None) != "42701":
            raise
    except OperationalError as exc:  # pragma: no cover - SQLite path
        if "duplicate column" not in str(exc).lower():
            raise
