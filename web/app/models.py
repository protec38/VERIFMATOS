# app/models.py — Modèles SQLAlchemy
from __future__ import annotations
import enum
from datetime import datetime, date
from typing import Optional, List

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import CheckConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from flask_login import UserMixin

from . import db

# -------------------------------------------------------------------
# Utilisateurs & rôles
# -------------------------------------------------------------------

class Role(enum.Enum):
    ADMIN = "admin"
    CHEF = "chef"
    VIEWER = "viewer"  # lecture seule

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(Role), nullable=False, default=Role.CHEF)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

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

# -------------------------------------------------------------------
# Événements & partage public
# -------------------------------------------------------------------

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

class EventShareLink(db.Model):
    __tablename__ = "event_share_links"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event", backref="share_links")

# -------------------------------------------------------------------
# Stock hiérarchique (≤ 5 niveaux)
# -------------------------------------------------------------------

class NodeType(enum.Enum):
    GROUP = "group"   # nœud parent
    ITEM  = "item"    # feuille vérifiable

class StockNode(db.Model):
    __tablename__ = "stock_nodes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.Enum(NodeType), nullable=False, default=NodeType.GROUP)
    level = db.Column(db.Integer, nullable=False, default=0)  # 0 = racine
    parent_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=True, index=True)
    parent = db.relationship("StockNode", remote_side=[id], backref="children")

    # Quantité cible pour les ITEMS uniquement
    quantity = db.Column(db.Integer, nullable=True)

    # Un parent peut être marqué comme "objet unique" (pas d'enfants, mais quantité max)
    unique_item = db.Column(db.Boolean, nullable=False, default=False)
    unique_quantity = db.Column(db.Integer, nullable=True)

    # (Legacy) Date de péremption simple. Gardée pour compatibilité ascendante.
    # Désormais on utilise StockItemExpiry pour plusieurs dates.
    expiry_date = db.Column(db.Date, nullable=True)

    # Relation vers les multiples dates de péremption
    expiries = db.relationship(
        "StockItemExpiry",
        backref="item",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("level >= 0 AND level <= 5", name="ck_stocknode_level_0_5"),
        CheckConstraint("(quantity IS NULL) OR (quantity >= 0)", name="ck_stocknode_qty_nonneg"),
        CheckConstraint(
            "(unique_quantity IS NULL) OR (unique_quantity >= 0)",
            name="ck_stocknode_unique_qty_nonneg",
        ),
    )

    def is_leaf(self) -> bool:
        return self.type == NodeType.ITEM

# Table des expirations multiples par ITEM
class StockItemExpiry(db.Model):
    __tablename__ = "stock_item_expiries"

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=False, index=True)
    expiry_date = db.Column(db.Date, nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=True)     # quantité concernée pour cette date (optionnel)
    lot = db.Column(db.String(64), nullable=True)       # n° de lot (optionnel)
    note = db.Column(db.String(255), nullable=True)     # commentaire (optionnel)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("(quantity IS NULL) OR (quantity >= 0)", name="ck_itemexpiry_qty_nonneg"),
    )

# Association : racines de stock attachées à un événement
event_stock = db.Table(
    "event_stock",
    db.Column("event_id", db.Integer, db.ForeignKey("events.id"), primary_key=True),
    db.Column("node_id", db.Integer, db.ForeignKey("stock_nodes.id"), primary_key=True),
    db.Column("selected_quantity", db.Integer, nullable=True),
)

# -------------------------------------------------------------------
# Vérifications d'items (historique)
# -------------------------------------------------------------------

class ItemStatus(enum.Enum):
    TODO = "todo"
    OK = "ok"
    NOT_OK = "not_ok"  # manquant / non conforme

# Motifs détaillés pour NOT_OK
class IssueCode(enum.Enum):
    BROKEN = "broken"    # cassé
    MISSING = "missing"  # manquant
    OTHER  = "other"     # autre (commentaire recommandé)

class VerificationRecord(db.Model):
    __tablename__ = "verification_records"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    node_id  = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=False, index=True)  # ITEM uniquement

    status = db.Column(db.Enum(ItemStatus), nullable=False, default=ItemStatus.OK)
    verifier_name = db.Column(db.String(120), nullable=False)  # saisi sur page publique ou par utilisateur connecté
    comment = db.Column(db.Text, nullable=True)

    # Champs étendus pour NOT_OK
    issue_code   = db.Column(db.Enum(IssueCode), nullable=True)  # requis si status == NOT_OK
    observed_qty = db.Column(db.Integer, nullable=True)          # quantité réellement constatée
    missing_qty  = db.Column(db.Integer, nullable=True)          # nombre manquant

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event", backref="verifications")
    node  = db.relationship("StockNode")

    __table_args__ = (
        Index("ix_verif_event_node_time", "event_id", "node_id", "created_at"),
        CheckConstraint("(observed_qty IS NULL) OR (observed_qty >= 0)", name="ck_verif_observed_nonneg"),
        CheckConstraint("(missing_qty  IS NULL) OR (missing_qty  >= 0)", name="ck_verif_missing_nonneg"),
    )

# -------------------------------------------------------------------
# Statut par parent pour l'événement (chargé dans véhicule)
# -------------------------------------------------------------------

class EventNodeStatus(db.Model):
    __tablename__ = "event_node_status"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    node_id  = db.Column(db.Integer, db.ForeignKey("stock_nodes.id"), nullable=False, index=True)  # GROUP uniquement

    charged_vehicle = db.Column(db.Boolean, default=False, nullable=False)
    comment = db.Column(db.Text, nullable=True)  # peut contenir "Véhicule: ..." + opérateur
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "node_id", name="uq_event_node_unique"),
    )

    event = db.relationship("Event")
    node  = db.relationship("StockNode")

# -------------------------------------------------------------------
# Journalisation minimale
# -------------------------------------------------------------------

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # pages publiques -> None
    action = db.Column(db.String(120), nullable=False)
    meta = db.Column(JSONB, nullable=True)

    user = db.relationship("User")
