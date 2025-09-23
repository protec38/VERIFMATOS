from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager

# ------------------------------------------------------------------
# ROLES
# ------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_CHEF = "chef"
ROLE_VIEWER = "viewer"

# ------------------------------------------------------------------
# MODELS (prefixe app_ pour éviter conflits PG)
# ------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "app_users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_ADMIN)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


class Item(db.Model):
    """
    Item hiérarchique multi-niveaux.
    kind: "parent" ou "leaf"
    expected_qty utilisé seulement pour les feuilles.
    icon: nom Font Awesome ex 'fa-kit-medical' (sans le 'fa-solid').
    """
    __tablename__ = "app_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, default="leaf")
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=True, index=True)
    expected_qty = db.Column(db.Integer, nullable=False, default=1)
    icon = db.Column(db.String(64), nullable=True)

    parent = db.relationship("Item", remote_side=[id], backref=db.backref("children", lazy="dynamic"))

    def is_parent(self) -> bool:
        return self.kind == "parent"

    def __repr__(self):
        return f"<Item {self.name}#{self.id} kind={self.kind}>"


class Event(db.Model):
    __tablename__ = "app_events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(255))
    state = db.Column(db.String(20), default="draft")
    token = db.Column(db.String(36), unique=True, index=True)  # lien partageable

    def __repr__(self):
        return f"<Event {self.title}#{self.id}>"


class EventParent(db.Model):
    """
    Lie un parent (Item.kind='parent') à un Event.
    """
    __tablename__ = "app_event_parents"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("event_parents", cascade="all, delete-orphan"))
    parent = db.relationship("Item")

    def __repr__(self):
        return f"<EventParent ev={self.event_id} parent={self.parent_id}>"


class EventChild(db.Model):
    """
    Feuilles incluses pour l'Event, vérifiables en live.
    """
    __tablename__ = "app_event_children"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    included = db.Column(db.Boolean, default=True)

    # état de vérification
    verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(120))
    verified_at = db.Column(db.DateTime)

    event = db.relationship("Event", backref=db.backref("event_children", cascade="all, delete-orphan"))
    child = db.relationship("Item")

    def __repr__(self):
        return f"<EventChild ev={self.event_id} child={self.child_id} verified={self.verified}>"


class EventLoad(db.Model):
    """
    Etat 'chargé' par parent (quand tous les enfants inclus sont vérifiés).
    """
    __tablename__ = "app_event_loads"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    loaded = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<EventLoad ev={self.event_id} parent={self.parent_id} loaded={self.loaded}>"


class EventPresence(db.Model):
    """
    Qui travaille sur quel parent (présence active).
    """
    __tablename__ = "app_event_presence"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    actor = db.Column(db.String(120), nullable=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Presence ev={self.event_id} parent={self.parent_id} actor={self.actor}>"


class EventLog(db.Model):
    """
    Journal d'activité pour audit/export.
    """
    __tablename__ = "app_event_logs"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    actor = db.Column(db.String(120))
    action = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship("Event", backref=db.backref("logs", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Log ev={self.event_id} by={self.actor} at={self.at} {self.action}>"


__all__ = [
    "ROLE_ADMIN", "ROLE_CHEF", "ROLE_VIEWER",
    "User", "Item", "Event", "EventParent", "EventChild", "EventLoad", "EventPresence", "EventLog",
]
