from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db

# -----------------------------------------------------
# Role constants
# -----------------------------------------------------
class Role:
    ADMIN = "admin"
    CHEF = "chef"
    SECOURISTE = "secouriste"
    VIEWER = "viewer"


# -----------------------------------------------------
# User model
# -----------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"  # ⚠️ éviter "user" réservé en SQL

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120))
    role = db.Column(
        db.Enum(
            Role.ADMIN, Role.CHEF, Role.SECOURISTE, Role.VIEWER,
            name="role_enum"
        ),
        nullable=False,
        default=Role.VIEWER,
    )
    is_active = db.Column(db.Boolean, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Gestion mot de passe
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f"<User {self.id} {self.email} role={self.role}>"


# -----------------------------------------------------
# Inventory Node
# -----------------------------------------------------
class InventoryNode(db.Model):
    __tablename__ = "inventory_node"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("inventory_node.id"), nullable=True)
    parent = db.relationship("InventoryNode", remote_side=[id], backref="children")
    name = db.Column(db.String(255), nullable=False)
    is_leaf = db.Column(db.Boolean, default=False, nullable=False)
    expected_qty = db.Column(db.Integer, nullable=True)
    icon = db.Column(db.String(64), nullable=True)
    path = db.Column(db.String(1024), index=True)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# -----------------------------------------------------
# Event
# -----------------------------------------------------
class Event(db.Model):
    __tablename__ = "event"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    event_date = db.Column(db.Date)
    location = db.Column(db.String(255))
    status = db.Column(
        db.Enum("draft", "preparing", "validated", name="event_status"),
        default="draft",
        nullable=False,
    )
    share_token = db.Column(db.String(64), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# -----------------------------------------------------
# Event Item
# -----------------------------------------------------
class EventItem(db.Model):
    __tablename__ = "event_item"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), index=True, nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey("inventory_node.id"), index=True, nullable=False)
    include = db.Column(db.Boolean, default=True, nullable=False)
    required_qty = db.Column(db.Integer, nullable=True)
    state = db.Column(
        db.Enum("pending", "checked", name="item_state"),
        default="pending",
        nullable=False,
    )
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    checked_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("event_id", "node_id", name="uq_event_node"),)


# -----------------------------------------------------
# Presence
# -----------------------------------------------------
class Presence(db.Model):
    __tablename__ = "presence"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    last_seen_at = db.Column(db.DateTime, index=True)
    device_info = db.Column(db.String(255))


# -----------------------------------------------------
# Activity Log
# -----------------------------------------------------
class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    target_node_id = db.Column(db.Integer, db.ForeignKey("inventory_node.id"), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
