from datetime import datetime
import secrets
from flask_login import UserMixin
from . import db

ROLE_ADMIN = "admin"
ROLE_CHEF = "chef"
ROLE_SECOURISTE = "secouriste"

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_SECOURISTE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    is_parent = db.Column(db.Boolean, default=False)
    expected_qty = db.Column(db.Integer, default=1)
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    children = db.relationship("Item", backref=db.backref("parent", remote_side=[id]))

class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(200))
    chef_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    state = db.Column(db.String(20), default="in_progress")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(32), unique=True, default=lambda: secrets.token_hex(8))
    chef = db.relationship("User", backref="events")

class EventItem(db.Model):
    __tablename__ = "event_items"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    loaded = db.Column(db.Boolean, default=False)
    parent = db.relationship("Item")

class EventInclude(db.Model):
    __tablename__ = "event_includes"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    leaf_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    included = db.Column(db.Boolean, default=True)
    parent = db.relationship("Item", foreign_keys=[parent_id])
    leaf = db.relationship("Item", foreign_keys=[leaf_id])

class Verification(db.Model):
    __tablename__ = "verifications"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    leaf_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    verified = db.Column(db.Boolean, default=False)
    by = db.Column(db.String(120))
    timestamp = db.Column(db.DateTime)
    leaf = db.relationship("Item")

class Activity(db.Model):
    __tablename__ = "activities"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    actor = db.Column(db.String(120))
    action = db.Column(db.String(50))
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    at = db.Column(db.DateTime, default=datetime.utcnow)
    item = db.relationship("Item")

class Presence(db.Model):
    __tablename__ = "presences"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    volunteer = db.Column(db.String(120))
    ping_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent = db.relationship("Item")
