# app/models.py
from __future__ import annotations
from datetime import datetime, date
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import (
    Column, Integer, String, Enum, Boolean, Date, DateTime, ForeignKey, Table,
    func, Index, UniqueConstraint, Text
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from . import db


# =========================
# Enums
# =========================
class Role(str, Enum):
    ADMIN = "ADMIN"
    CHEF = "CHEF"
    VIEWER = "VIEWER"


class NodeType(str, Enum):
    GROUP = "GROUP"
    ITEM = "ITEM"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# Présent pour compat reports/utils & calculs
class ItemStatus(str, Enum):
    OK = "OK"
    NOT_OK = "NOT_OK"
    PENDING = "PENDING"


# =========================
# User
# =========================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False, default=Role.ADMIN)
    # actif ou non (Flask-Login utilisera la property is_active, ci-dessous)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )

    # Flask-Login glue
    @property
    def is_active(self) -> bool:  # ne pas setter; Flask-Login lit seulement
        return bool(self.active)

    def get_id(self) -> str:
        return str(self.id)


# =========================
# Arbre de stock
# =========================
class StockNode(db.Model):
    __tablename__ = "stock_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[NodeType] = mapped_column(Enum(NodeType), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stock_nodes.id"), nullable=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    parent = relationship("StockNode", remote_side=[id], backref="children", lazy="joined")


# =========================
# Événements
# =========================
class Event(db.Model):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), nullable=False, default=EventStatus.OPEN)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_by = relationship("User", lazy="joined")


# Association: évènement ↔ racines à vérifier
event_stock = Table(
    "event_stock",
    db.metadata,
    Column("event_id", Integer, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("node_id", Integer, ForeignKey("stock_nodes.id", ondelete="CASCADE"), primary_key=True),
)


# =========================
# Lien de partage public
# =========================
class EventShareLink(db.Model):
    __tablename__ = "event_share_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event = relationship("Event", lazy="joined")

    __table_args__ = (
        UniqueConstraint("token", name="uq_share_token"),
    )


# =========================
# État par parent dans l'événement (chargé etc.)
# =========================
class EventNodeStatus(db.Model):
    __tablename__ = "event_node_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    # ancien champ présent dans ton code
    charged_vehicle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # >>> Nouveaux champs pour “Chargé dans véhicule”
    charged_vehicle_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)  # ex. VSAV-1
    charged_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)            # qui a cliqué
    charged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optionnel : note libre / anomalie parent
    note: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)

    event = relationship("Event", lazy="joined")
    node = relationship("StockNode", lazy="joined")

    __table_args__ = (
        Index("ix_event_node_status_event_id", "event_id"),
        Index("ix_event_node_status_node_id", "node_id"),
        UniqueConstraint("event_id", "node_id", name="uq_event_node_status_unique"),
    )


# =========================
# Vérifications (historique)
# =========================
class VerificationRecord(db.Model):
    __tablename__ = "verification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), nullable=False)
    verifier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    event = relationship("Event", lazy="joined")
    node = relationship("StockNode", lazy="joined")

    __table_args__ = (
        Index("ix_verif_event_node_time", "event_id", "node_id", "created_at"),
    )


# =========================
# Audit (optionnel)
# =========================
class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=True)
    node_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stock_nodes.id", ondelete="CASCADE"), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event = relationship("Event", lazy="joined")
    node = relationship("StockNode", lazy="joined")
