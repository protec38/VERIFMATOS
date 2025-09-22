# app/models.py
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager

# ============================================================
# RÔLES (constants)
# ============================================================
ROLE_ADMIN = "admin"
ROLE_CHEF = "chef"
ROLE_VIEWER = "viewer"

def utcnow():
    return datetime.utcnow()

# ============================================================
# USER
# ============================================================
class User(UserMixin, db.Model):
    __tablename__ = "app_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_ADMIN)  # admin / chef / viewer
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# ============================================================
# ITEM (hiérarchie multi-niveaux)
# ============================================================
class Item(db.Model):
    __tablename__ = "app_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, default="leaf")  # parent / leaf
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=True)
    expected_qty = db.Column(db.Integer, nullable=False, default=1)
    icon = db.Column(db.String(64), nullable=True)  # ex: "fa-kit-medical"

    parent = db.relationship(
        "Item",
        remote_side=[id],
        backref=db.backref("children", lazy="dynamic", cascade="all")
    )

    def is_parent(self) -> bool:
        return self.kind == "parent"

    def __repr__(self) -> str:
        return f"<Item {self.id} {self.name} kind={self.kind} parent_id={self.parent_id}>"

# ============================================================
# EVENT
# ============================================================
class Event(db.Model):
    __tablename__ = "app_events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    date = db.Column(db.DateTime, default=utcnow, index=True)
    location = db.Column(db.String(255))
    state = db.Column(db.String(20), default="draft")
    token = db.Column(db.String(64), unique=True, index=True)  # lien partageable

    __table_args__ = (
        db.Index("ix_app_events_state_date", "state", "date"),
    )

    def __repr__(self) -> str:
        return f"<Event {self.id} {self.title} ({self.state})>"

# ============================================================
# EVENT ↔ PARENTS ASSOCIÉS
# ============================================================
class EventParent(db.Model):
    __tablename__ = "app_event_parents"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    event = db.relationship(
        "Event",
        backref=db.backref("event_parents", cascade="all, delete-orphan", lazy="dynamic")
    )
    parent = db.relationship("Item")

    __table_args__ = (
        db.UniqueConstraint("event_id", "parent_id", name="uq_app_event_parents_event_parent"),
    )

    def __repr__(self) -> str:
        return f"<EventParent ev={self.event_id} parent={self.parent_id}>"

# ============================================================
# EVENT ↔ FEUILLES INCLUSES + VÉRIF LIVE
# ============================================================
class EventChild(db.Model):
    __tablename__ = "app_event_children"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    included = db.Column(db.Boolean, default=True)

    verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(120))
    verified_at = db.Column(db.DateTime)

    event = db.relationship(
        "Event",
        backref=db.backref("event_children", cascade="all, delete-orphan", lazy="dynamic")
    )
    child = db.relationship("Item")

    __table_args__ = (
        db.UniqueConstraint("event_id", "child_id", name="uq_app_event_children_event_child"),
    )

    def __repr__(self) -> str:
        return (
            f"<EventChild ev={self.event_id} child={self.child_id} "
            f"included={self.included} verified={self.verified}>"
        )

# ============================================================
# CHARGEMENT DES PARENTS
# ============================================================
class EventLoad(db.Model):
    __tablename__ = "app_event_loads"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    loaded = db.Column(db.Boolean, default=False)

    event = db.relationship(
        "Event",
        backref=db.backref("loads", cascade="all, delete-orphan", lazy="dynamic")
    )

    __table_args__ = (
        db.UniqueConstraint("event_id", "parent_id", name="uq_app_event_loads_event_parent"),
    )

    def __repr__(self) -> str:
        return f"<EventLoad ev={self.event_id} parent={self.parent_id} loaded={self.loaded}>"

# ============================================================
# PRÉSENCE (qui travaille sur quel parent)
# ============================================================
class EventPresence(db.Model):
    __tablename__ = "app_event_presence"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    actor = db.Column(db.String(120), nullable=False, index=True)
    last_seen = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, index=True)

    event = db.relationship(
        "Event",
        backref=db.backref("presence", cascade="all, delete-orphan", lazy="dynamic")
    )

    __table_args__ = (
        db.Index("ix_app_event_presence_actor_parent", "actor", "parent_id"),
    )

    def __repr__(self) -> str:
        return f"<Presence ev={self.event_id} parent={self.parent_id} {self.actor} at={self.last_seen}>"

# ============================================================
# LOGS
# ============================================================
class EventLog(db.Model):
    __tablename__ = "app_event_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    actor = db.Column(db.String(120))
    action = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=utcnow, index=True)

    event = db.relationship(
        "Event",
        backref=db.backref("logs", cascade="all, delete-orphan", lazy="dynamic")
    )

    def __repr__(self) -> str:
        return f"<Log ev={self.event_id} {self.actor} {self.action} at={self.at}>"

# ============================================================
# ALIASES RÉTRO-COMPAT
# (pour d'anciens imports dans events.py)
# ============================================================
EventItem = EventChild
EventInclude = EventChild
EventLeaf = EventChild
EventCheck = EventChild
Verification = EventChild  # ✅ nouvel alias pour corriger l'import

__all__ = [
    # consts
    "ROLE_ADMIN", "ROLE_CHEF", "ROLE_VIEWER",
    # models
    "User", "Item", "Event", "EventParent", "EventChild",
    "EventLoad", "EventPresence", "EventLog",
    # retro aliases
    "EventItem", "EventInclude", "EventLeaf", "EventCheck", "Verification",
]
