# app/models.py
from __future__ import annotations
from datetime import datetime, date
from enum import Enum
from typing import Optional

from werkzeug.security import generate_password_hash, check_password_hash

from . import db


# ---------- Enums "métier" ----------
class Role(str, Enum):
    ADMIN = "ADMIN"
    CHEF = "CHEF"
    VIEWER = "VIEWER"


class NodeType(str, Enum):
    GROUP = "GROUP"   # sac, ambulance, caisse...
    ITEM = "ITEM"     # élément vérifiable (compresses, tensiomètre...)


class EventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ---------- Utilisateur ----------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum(Role, values_callable=lambda x: [e.value for e in x]), nullable=False, default=Role.VIEWER)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Flask-Login compatibility
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    # password helpers
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


# ---------- Audit (optionnel) ----------
class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    meta = db.Column(db.Text, nullable=True)

    user = db.relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<Audit {self.action} by {self.user_id} at {self.at}>"


# ---------- Stock hiérarchique ----------
class StockNode(db.Model):
    __tablename__ = "stock_nodes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.Enum(NodeType, values_callable=lambda x: [e.value for e in x]), nullable=False, default=NodeType.GROUP)
    quantity = db.Column(db.Integer, nullable=True)  # pour ITEM; None pour GROUP
    level = db.Column(db.Integer, nullable=False, default=0)

    parent_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=True)

    # hiérarchie
    parent = db.relationship(
        "StockNode",
        remote_side=[id],
        backref=db.backref("children", cascade="all, delete-orphan", lazy="selectin"),
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<StockNode {self.id} {self.name} ({self.type}) lvl={self.level}>"


# ---------- Évènements & associations ----------
event_stock = db.Table(
    "event_stock",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    db.Column("node_id", db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), primary_key=True),
)

class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=True)

    status = db.Column(db.Enum(EventStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=EventStatus.OPEN)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_by = db.relationship("User", lazy="joined")

    # Parents racine associés à l'évènement
    roots = db.relationship(
        "StockNode",
        secondary=event_stock,
        lazy="selectin",
        backref=db.backref("events", lazy="selectin"),
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Event {self.id} {self.name} ({self.status})>"


class EventShareLink(db.Model):
    __tablename__ = "event_share_links"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    event = db.relationship("Event", lazy="joined")

    def __repr__(self) -> str:
        return f"<ShareLink {self.token[:7]}… for event {self.event_id}>"


class EventNodeStatus(db.Model):
    """
    Statut par parent pour un évènement :
    - charged_vehicle : bool (chargé/ non chargé)
    - vehicle_name    : str (VSAV 1, VL, REM 2…)
    """
    __tablename__ = "event_node_status"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    charged_vehicle = db.Column(db.Boolean, nullable=False, default=False)
    vehicle_name = db.Column(db.String(120), nullable=True)

    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    event = db.relationship("Event", lazy="joined")
    node = db.relationship("StockNode", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("event_id", "node_id", name="uq_event_node_status"),
    )

    def __repr__(self) -> str:
        return f"<ENS ev={self.event_id} node={self.node_id} charged={self.charged_vehicle} vehicle={self.vehicle_name!r}>"


class VerificationRecord(db.Model):
    """
    Enregistrements de vérification pour chaque ITEM.
    NB: on stocke 'status' en texte ('OK' / 'NOT_OK') pour éviter
    tout problème de sérialisation JSON côté API.
    """
    __tablename__ = "verification_records"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    status = db.Column(db.String(16), nullable=False)  # "OK" or "NOT_OK"
    verifier_name = db.Column(db.String(200), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    event = db.relationship("Event", lazy="joined")
    node = db.relationship("StockNode", lazy="joined")

    __table_args__ = (
        db.Index("ix_verif_event_node_time", "event_id", "node_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Verif ev={self.event_id} node={self.node_id} {self.status} by {self.verifier_name} at {self.created_at}>"
