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

        _ensure_stock_root_categories_table(conn, tables)

        if "stock_nodes" in tables:
            _ensure_stock_nodes_columns(conn, inspector)

        if "event_stock" in tables:
            _ensure_event_stock_columns(conn, inspector)

        _ensure_event_template_tables(conn, tables)
        _ensure_event_material_slots_table(conn, tables)
        _ensure_reassort_tables(conn)
        _ensure_periodic_verification_table(conn)
        _ensure_periodic_session_tables(conn)
        _ensure_audit_table(conn)
        _ensure_role_enum_value(conn)


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

    if "root_category_id" not in columns:
        current_app.logger.info("Adding column stock_nodes.root_category_id")
        _execute_ignore_duplicate(
            conn,
            "ALTER TABLE stock_nodes ADD COLUMN root_category_id INTEGER",
        )
        _execute_ignore_duplicate(
            conn,
            "CREATE INDEX IF NOT EXISTS ix_stock_nodes_root_category_id ON stock_nodes(root_category_id)",
        )


def _ensure_stock_root_categories_table(conn: Connection, tables: set[str]) -> None:
    try:
        from .models import StockRootCategory  # type: ignore
    except Exception:
        return

    if "stock_root_categories" not in tables:
        current_app.logger.info("Creating table stock_root_categories")

    try:
        StockRootCategory.__table__.create(bind=conn, checkfirst=True)
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning(
            "Unable to ensure stock_root_categories table: %s", exc
        )


def _ensure_event_stock_columns(conn: Connection, inspector) -> None:
    columns = {col["name"] for col in inspector.get_columns("event_stock")}

    if "selected_quantity" not in columns:
        current_app.logger.info("Adding column event_stock.selected_quantity")
        _execute_ignore_duplicate(
            conn,
            "ALTER TABLE event_stock ADD COLUMN selected_quantity INTEGER",
        )


def _ensure_event_template_tables(conn: Connection, tables: set[str]) -> None:
    from .models import EventTemplate, EventTemplateNode  # import tardif pour éviter les cycles

    if "event_templates" not in tables:
        current_app.logger.info("Creating table event_templates")
    EventTemplate.__table__.create(bind=conn, checkfirst=True)

    if "event_template_nodes" not in tables:
        current_app.logger.info("Creating table event_template_nodes")
    EventTemplateNode.__table__.create(bind=conn, checkfirst=True)


def _ensure_event_material_slots_table(conn: Connection, tables: set[str]) -> None:
    try:
        from .models import EventMaterialSlot  # import tardif pour éviter les cycles
    except Exception:
        return

    if "event_material_slots" not in tables:
        current_app.logger.info("Creating table event_material_slots")

    try:
        EventMaterialSlot.__table__.create(bind=conn, checkfirst=True)
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning("Unable to ensure event_material_slots table: %s", exc)


def _ensure_reassort_tables(conn: Connection) -> None:
    try:
        from .models import ReassortItem, ReassortBatch  # import tardif
    except Exception:
        return

    try:
        ReassortItem.__table__.create(bind=conn, checkfirst=True)
        ReassortBatch.__table__.create(bind=conn, checkfirst=True)
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning("Unable to ensure reassort tables: %s", exc)


def _ensure_periodic_verification_table(conn: Connection) -> None:
    try:
        from .models import PeriodicVerificationRecord  # import tardif
    except Exception:
        return

    try:
        PeriodicVerificationRecord.__table__.create(bind=conn, checkfirst=True)
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning("Unable to ensure periodic verification table: %s", exc)


def _ensure_periodic_session_tables(conn: Connection) -> None:
    try:
        from .models import PeriodicVerificationLink, PeriodicVerificationSession  # import tardif
    except Exception:
        return

    for model in (PeriodicVerificationLink, PeriodicVerificationSession):
        try:
            model.__table__.create(bind=conn, checkfirst=True)
        except Exception as exc:  # pragma: no cover - garde-fou
            current_app.logger.warning("Unable to ensure %s table: %s", model.__tablename__, exc)


def _ensure_audit_table(conn: Connection) -> None:
    try:
        from .models import AuditLog  # import tardif
    except Exception:
        return

    try:
        AuditLog.__table__.create(bind=conn, checkfirst=True)
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning("Unable to ensure audit log table: %s", exc)


def _ensure_role_enum_value(conn: Connection) -> None:
    """Ensure the Role enum accepts the VERIFICATIONPERIODIQUE value (PostgreSQL)."""
    try:
        if conn.dialect.name != "postgresql":
            return
    except Exception:  # pragma: no cover - defensive
        return

    try:
        row = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='role' LIMIT 1"
            )
        ).fetchone()
    except Exception:  # pragma: no cover - defensive
        return

    if not row or not row[0]:
        return

    type_name = row[0]
    def _label_exists(label: str) -> bool:
        try:
            existing = conn.execute(
                text(
                    "SELECT 1 FROM pg_type t "
                    "JOIN pg_enum e ON t.oid = e.enumtypid "
                    "WHERE t.typname = :type AND e.enumlabel = :label"
                ),
                {"type": type_name, "label": label},
            ).fetchone()
        except Exception:  # pragma: no cover - defensive
            return False
        return bool(existing)

    desired_label = "VERIFICATIONPERIODIQUE"
    legacy_label = "verificationperiodique"

    if _label_exists(desired_label):
        return

    quoted_type = f'"{type_name}"'

    if _label_exists(legacy_label):
        try:
            conn.execute(
                text(
                    f"ALTER TYPE {quoted_type} RENAME VALUE '{legacy_label}' "
                    f"TO '{desired_label}'"
                )
            )
            return
        except Exception as exc:  # pragma: no cover - fallback if rename unsupported
            current_app.logger.warning(
                "Unable to rename legacy role enum value: %s", exc
            )

    try:
        conn.execute(
            text(
                f"ALTER TYPE {quoted_type} ADD VALUE IF NOT EXISTS '{desired_label}'"
            )
        )
    except ProgrammingError:
        conn.execute(text(f"ALTER TYPE {quoted_type} ADD VALUE '{desired_label}'"))
    except Exception as exc:  # pragma: no cover - garde-fou
        current_app.logger.warning("Unable to extend role enum: %s", exc)

def _execute_ignore_duplicate(conn: Connection, sql: str) -> None:
    try:
        conn.execute(text(sql))
    except ProgrammingError as exc:  # pragma: no cover - defensive
        if getattr(getattr(exc, "orig", None), "pgcode", None) != "42701":
            raise
    except OperationalError as exc:  # pragma: no cover - SQLite path
        if "duplicate column" not in str(exc).lower():
            raise
