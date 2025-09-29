from __future__ import annotations

import enum
from datetime import datetime, date
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class Role(enum.Enum):
    ADMIN = "ADMIN"
    CHEF = "CHEF"
    VIEWER = "VIEWER"


class EventStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NodeType(enum.Enum):
    GROUP = "GROUP"
    ITEM = "ITEM"


# Présent pour compat (certains modules importent ItemStatus depuis models)
class ItemStatus(enum.Enum):
    OK = "OK"
    NOT_OK = "NOT_OK"


# -----------------------------------------------------------------------------
# Modèles
# -----------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)
    username: str = db.Column(db.String(80), unique=True, index=True, nullable=False)
    password_hash: str = db.Column(db.String(255), nullable=False)
    role: Role = db.Column(db.Enum(Role), nullable=False, default=Role.VIEWER)

    # Ajoutés / garantis par __init__.py avec ALTER TABLE IF NOT EXISTS
    created_at: datetime = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now()
    )
    active: bool = db.Column(db.Boolean, nullable=False, default=True)

    # ---- helpers password
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    # ---- Flask-Login bridge (évite l'AttributeError du seeding)
    @property
    def is_active(self) -> bool:  # Flask-Login lit ceci
        return bool(self.active)

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self.active = bool(value)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.name})>"


class StockNode(db.Model):
    __tablename__ = "stock_nodes"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(255), nullable=False)
    type: NodeType = db.Column(db.Enum(NodeType), nullable=False, default=NodeType.GROUP)
    level: int = db.Column(db.Integer, nullable=False, default=0)

    parent_id: Optional[int] = db.Column(
        db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=True
    )
    parent = db.relationship(
        "StockNode", remote_side=[id], backref=db.backref("children", cascade="all, delete-orphan")
    )

    quantity: Optional[int] = db.Column(db.Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<StockNode {self.id} {self.name} ({self.type.name}) lvl={self.level}>"


# Association événement <-> parents racine sélectionnés
event_stock = db.Table(
    "event_stock",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    db.Column("node_id", db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), primary_key=True),
)


class Event(db.Model):
    __tablename__ = "events"

    id: int = db.Column(db.Integer, primary_key=True)
    name: str = db.Column(db.String(255), nullable=False)
    date: Optional[date] = db.Column(db.Date, nullable=True)
    status: EventStatus = db.Column(db.Enum(EventStatus), nullable=False, default=EventStatus.OPEN)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now()
    )

    created_by_id: Optional[int] = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # parents racine rattachés
    roots = db.relationship(
        "StockNode",
        secondary=event_stock,
        backref=db.backref("events", lazy="dynamic"),
        lazy="subquery",
    )

    def __repr__(self) -> str:
        return f"<Event {self.id} {self.name} ({self.status.name})>"


class EventShareLink(db.Model):
    __tablename__ = "event_share_links"

    id: int = db.Column(db.Integer, primary_key=True)
    event_id: int = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    event = db.relationship("Event", backref=db.backref("share_links", cascade="all, delete-orphan"))

    token: str = db.Column(db.String(64), unique=True, index=True, nullable=False)
    active: bool = db.Column(db.Boolean, nullable=False, default=True)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now()
    )

    def __repr__(self) -> str:
        return f"<ShareLink ev={self.event_id} token={self.token[:8]} active={self.active}>"


class EventNodeStatus(db.Model):
    """
    Statut côté événement pour un parent (ex: chargé dans véhicule + nom du véhicule).
    Unicité par (event_id, node_id).
    """
    __tablename__ = "event_node_status"

    id: int = db.Column(db.Integer, primary_key=True)
    event_id: int = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: int = db.Column(db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    charged_vehicle: bool = db.Column(db.Boolean, nullable=False, default=False)
    vehicle_name: Optional[str] = db.Column(db.String(120), nullable=True)

    event = db.relationship("Event", backref=db.backref("node_statuses", cascade="all, delete-orphan"))
    node = db.relationship("StockNode")

    __table_args__ = (
        db.UniqueConstraint("event_id", "node_id", name="uq_event_node"),
    )

    def __repr__(self) -> str:
        return f"<EventNodeStatus ev={self.event_id} node={self.node_id} charged={self.charged_vehicle}>"


class VerificationRecord(db.Model):
    """
    Historique des vérifications des ITEMS (OK/NOT_OK) + nom du vérificateur.
    On garde 'status' en STRING pour éviter les soucis de JSON avec Enum.
    """
    __tablename__ = "verification_records"

    id: int = db.Column(db.Integer, primary_key=True)
    event_id: int = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: int = db.Column(db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    status: str = db.Column(db.String(8), nullable=False)  # "OK" | "NOT_OK"
    verifier_name: Optional[str] = db.Column(db.String(120), nullable=True)

    created_at: datetime = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now(), index=True
    )

    event = db.relationship("Event", backref=db.backref("verifications", cascade="all, delete-orphan"))
    node = db.relationship("StockNode")

    __table_args__ = (
        db.Index("ix_verif_event_node_time", "event_id", "node_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Verif ev={self.event_id} node={self.node_id} {self.status} by={self.verifier_name}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: int = db.Column(db.Integer, primary_key=True)
    at: datetime = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    user_id: Optional[int] = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: str = db.Column(db.Text, nullable=False)

    user = db.relationship("User")

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} user={self.user_id} at={self.at}>"
