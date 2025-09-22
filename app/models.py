from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import secrets

db = SQLAlchemy()

# ---------------------------------------------------------------------
# Constantes pour les rôles
# ---------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_CHEF = "chef"
ROLE_SECOURISTE = "secouriste"

# ---------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_SECOURISTE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    is_parent = db.Column(db.Boolean, default=False)
    expected_qty = db.Column(db.Integer, default=1)

    # relation hiérarchique parent → enfants
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    children = db.relationship("Item", backref=db.backref("parent", remote_side=[id]))

    def __repr__(self):
        return f"<Item {self.name} ({'parent' if self.is_parent else 'child'})>"


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(200))
    chef_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    state = db.Column(db.String(20), default="draft")  # draft, in_progress, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(32), unique=True, default=lambda: secrets.token_hex(8))

    chef = db.relationship("User", backref="events")
    event_items = db.relationship("EventItem", backref="event", cascade="all,delete-orphan")
    event_children = db.relationship("EventChild", backref="event", cascade="all,delete-orphan")
    verifications = db.relationship("Verification", backref="event", cascade="all,delete-orphan")
    activities = db.relationship("Activity", backref="event", cascade="all,delete-orphan")
    presences = db.relationship("Presence", backref="event", cascade="all,delete-orphan")

    def __repr__(self):
        return f"<Event {self.id} {self.title}>"


class EventItem(db.Model):
    __tablename__ = "event_items"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    loaded = db.Column(db.Boolean, default=False)

    item = db.relationship("Item")

    def __repr__(self):
        return f"<EventItem ev={self.event_id} item={self.item_id} loaded={self.loaded}>"


class EventChild(db.Model):
    __tablename__ = "event_children"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    child_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    included = db.Column(db.Boolean, default=True)

    parent = db.relationship("Item", foreign_keys=[parent_id], backref="event_children_parent")
    child = db.relationship("Item", foreign_keys=[child_id], backref="event_children_child")

    def __repr__(self):
        return f"<EventChild ev={self.event_id} parent={self.parent_id} child={self.child_id}>"


class Verification(db.Model):
    __tablename__ = "verifications"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    verified = db.Column(db.Boolean, default=False)
    by = db.Column(db.String(120))  # nom/prénom du secouriste
    timestamp = db.Column(db.DateTime)  # quand la case a été cochée

    item = db.relationship("Item")

    def __repr__(self):
        return f"<Verification ev={self.event_id} item={self.item_id} verified={self.verified}>"


class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    actor = db.Column(db.String(120))
    action = db.Column(db.String(50))
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    at = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship("Item")

    def __repr__(self):
        return f"<Activity ev={self.event_id} {self.actor} {self.action}>"


class Presence(db.Model):
    __tablename__ = "presences"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    volunteer = db.Column(db.String(120))
    ping_at = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship("Item")

    def __repr__(self):
        return f"<Presence ev={self.event_id} parent={self.parent_id} vol={self.volunteer}>"
