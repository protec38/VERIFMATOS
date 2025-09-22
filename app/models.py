from datetime import datetime
from flask_login import UserMixin
from . import db, login_manager
from werkzeug.security import generate_password_hash, check_password_hash

# ------------------------------------------------------------------
# Rôles (constants) — pour compatibilité avec des imports existants
# ------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_CHEF = "chef"
ROLE_VIEWER = "viewer"

# ------------------------------------------------------------------
# MODELES avec noms de tables sûrs (prefixe app_)
# ------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "app_users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_ADMIN)  # admin / chef / viewer
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Item(db.Model):
    __tablename__ = "app_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # kind: parent / leaf
    kind = db.Column(db.String(10), nullable=False, default="leaf")
    # hiérarchie multi-niveaux : parent -> sous-parent -> leaf
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=True)
    # quantité attendue pour vérification (seulement pour les feuilles)
    expected_qty = db.Column(db.Integer, nullable=False, default=1)
    # optionnel: icône FontAwesome (ex: "fa-kit-medical")
    icon = db.Column(db.String(64), nullable=True)

    parent = db.relationship("Item", remote_side=[id], backref=db.backref("children", lazy="dynamic"))

    def is_parent(self):
        return self.kind == "parent"


class Event(db.Model):
    __tablename__ = "app_events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(255))
    state = db.Column(db.String(20), default="draft")
    token = db.Column(db.String(36), unique=True, index=True)  # lien partageable


class EventParent(db.Model):
    __tablename__ = "app_event_parents"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("event_parents", cascade="all, delete-orphan"))
    parent = db.relationship("Item")


class EventChild(db.Model):
    __tablename__ = "app_event_children"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)

    # inclusion (le chef peut décocher certaines feuilles dans un parent)
    included = db.Column(db.Boolean, default=True)

    # vérification live
    verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(120))
    verified_at = db.Column(db.DateTime)

    event = db.relationship("Event", backref=db.backref("event_children", cascade="all, delete-orphan"))
    child = db.relationship("Item")


class EventLoad(db.Model):
    __tablename__ = "app_event_loads"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    loaded = db.Column(db.Boolean, default=False)


class EventPresence(db.Model):
    __tablename__ = "app_event_presence"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("app_items.id"), nullable=False, index=True)
    actor = db.Column(db.String(120), nullable=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EventLog(db.Model):
    __tablename__ = "app_event_logs"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("app_events.id"), nullable=False, index=True)
    actor = db.Column(db.String(120))
    action = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow)

    event = db.relationship("Event", backref=db.backref("logs", cascade="all, delete-orphan"))
