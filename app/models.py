from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Enum, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from .database import Base
import enum
import uuid

def gen_id():
    return str(uuid.uuid4())

class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    CHEF = "CHEF"
    SECOURISTE = "SECOURISTE"

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.CHEF, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ItemType(str, enum.Enum):
    UNIQUE = "UNIQUE"  # e.g., DAE (serial number)
    BULK = "BULK"      # consumable with quantity
    KIT = "KIT"        # parent like SAC PS

class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[ItemType] = mapped_column(Enum(ItemType), default=ItemType.BULK)
    # For UNIQUE items
    serial_number: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    # For BULK items
    stock_qty: Mapped[int] = mapped_column(Integer, default=0)

class KitItem(Base):
    __tablename__ = "kit_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    kit_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"))
    component_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"))
    required_qty: Mapped[int] = mapped_column(Integer, default=1)
    UniqueConstraint("kit_id","component_id", name="uq_kit_component")

    kit = relationship("Item", foreign_keys=[kit_id])
    component = relationship("Item", foreign_keys=[component_id])

class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    title: Mapped[str] = mapped_column(String, index=True)
    location: Mapped[str] = mapped_column(String, default="")
    start_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    chief_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    access_code: Mapped[str] = mapped_column(String, unique=True, index=True)  # token for share link
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class EventKit(Base):
    __tablename__ = "event_kits"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"))
    kit_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"))  # the KIT selected
    loaded: Mapped[bool] = mapped_column(Boolean, default=False)

class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"))
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    joined_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

class CheckStatus(str, enum.Enum):
    OK = "OK"
    MISSING = "MISSING"
    DAMAGED = "DAMAGED"

class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"))
    kit_id: Mapped[str | None] = mapped_column(String, ForeignKey("items.id"), nullable=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("items.id"))
    qty_checked: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CheckStatus] = mapped_column(Enum(CheckStatus), default=CheckStatus.OK)
    comment: Mapped[str] = mapped_column(Text, default="")
    verified_by: Mapped[str] = mapped_column(String)  # participant name
    verified_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

