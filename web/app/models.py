# app/models.py — Modèles SQLAlchemy
from __future__ import annotations
import enum
from datetime import datetime
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import CheckConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from flask_login import UserMixin
from . import db

# ---- Rôles utilisateurs ----
class Role(enum.Enum):
    ADMIN = "admin"
    CHEF = "chef"
    VIEWER = "viewer"  # lecture seule
...

    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(Role), nullable=False, default=Role.CHEF)
    is_active = db.Column(db.Boolean, default=True)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def can_manage_users(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_manage_events(self) -> bool:
        return self.role in (Role.ADMIN, Role.CHEF)

# ---- Événements ----
class EventStatus(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"

class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=True)
    status = db.Column(db.Enum(EventStatus), nullable=False, default=EventStatus.OPEN)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_by = db.relationship("User", backref="events")

# Lien public de partage pour secouristes (pas de compte requis)
class EventShareLink(db.Model):
    __tablename__ = "event_share_links"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    event = db.relationship("Event", backref="share_links")

# ---- Stock hiérarchique ≤ 5 niveaux ----
class NodeType(enum.Enum):
    GROUP = "group"  # parent/sous-parent/sous-sous-...
    ITEM = "item"    # enfant vérifiable avec quantité

class StockNode(db.Model):
    __tablename__ = "stock_nodes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.Enum(NodeType), nullable=False, default=NodeType.GROUP)
    # 0 = racine (ex: SAC PS BLEU, AMBULANCE 1, TABLE, CHAISE...)
    level = db.Column(db.Integer, nullable=False, default=0)
    parent_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=True)
    parent = db.relationship("StockNode", remote_side=[id], backref="children")
    # quantité uniquement pertinente pour ITEM
    quantity = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 5", name="ck_level_0_5"),
    )

    def is_leaf(self) -> bool:
        return self.type == NodeType.ITEM

# Association: sélection des racines de stock pour un événement
event_stock = db.Table(
    "event_stock",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id"), primary_key=True),
    db.Column("node_id", db.Integer, db.ForeignKey("stock_nodes.id"), primary_key=True),
)

# ---- Vérifications / temps réel ----
class ItemStatus(enum.Enum):
    TODO = "todo"
    OK = "ok"
    NOT_OK = "not_ok"  # manquant / non conforme

# ---- [NOUVEAU] Codes motif pour NOT_OK ----
class IssueCode(enum.Enum):
    BROKEN = "broken"     # cassé
    MISSING = "missing"   # manquant
    OTHER = "other"       # autre

# Historique des vérifications d'items (enfants)
class VerificationRecord(db.Model):
    __tablename__ = "verification_records"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    node_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=False, index=True)  # ITEM uniquement
    status = db.Column(db.Enum(ItemStatus), nullable=False, default=ItemStatus.OK)
    verifier_name = db.Column(db.String(120), nullable=False)  # saisi sur la page publique
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # ---- [NOUVEAU] Champs pour motifs/quantités quand NOT_OK ----
    issue_code = db.Column(db.Enum(IssueCode), nullable=True)  # seulement si NOT_OK
    observed_qty = db.Column(db.Integer, nullable=True)        # quantité réellement constatée
    missing_qty  = db.Column(db.Integer, nullable=True)        # nombre manquant

    event = db.relationship("Event", backref="verifications")
    node = db.relationship("StockNode")

    __table_args__ = (
        Index("ix_verif_event_node_time", "event_id", "node_id", "created_at"),
    )

# Statut par parent pour l'événement (ex: 'Chargé dans le véhicule')
class EventNodeStatus(db.Model):
    __tablename__ = "event_node_status"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    node_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=False, index=True)  # GROUP uniquement
    charged_vehicle = db.Column(db.Boolean, default=False, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "node_id", name="uq_event_node_unique"),
    )

    event = db.relationship("Event")
    node = db.relationship("StockNode")

# ---- Audit minimal (RGPD/export possible) ----
class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # public pages -> null
    action = db.Column(db.String(120), nullable=False)
    meta = db.Column(JSONB, nullable=True)

    user = db.relationship("User")
