from datetime import datetime, date
from .extensions import db

# Role constants
class Role:
    ADMIN = 'admin'
    CHEF = 'chef'
    SECOURISTE = 'secouriste'
    VIEWER = 'viewer'

class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.String(1024))

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120))
    role = db.Column(db.String(32), nullable=False, default=Role.VIEWER)
    is_active = db.Column(db.Boolean, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Flask-Login compatibility
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class InventoryNode(db.Model):
    __tablename__ = 'inventory_node'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('inventory_node.id'), nullable=True)
    parent = db.relationship('InventoryNode', remote_side=[id], backref='children')
    name = db.Column(db.String(255), nullable=False)
    is_leaf = db.Column(db.Boolean, default=False, nullable=False)
    expected_qty = db.Column(db.Integer, nullable=True)
    icon = db.Column(db.String(64), nullable=True)
    path = db.Column(db.String(1024), index=True)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Event(db.Model):
    __tablename__ = 'event'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    event_date = db.Column(db.Date)
    location = db.Column(db.String(255))
    status = db.Column(db.String(32), default='draft', nullable=False)  # draft/preparing/validated
    share_token = db.Column(db.String(64), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class EventItem(db.Model):
    __tablename__ = 'event_item'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), index=True, nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey('inventory_node.id'), index=True, nullable=False)
    include = db.Column(db.Boolean, default=True, nullable=False)
    required_qty = db.Column(db.Integer, nullable=True)
    state = db.Column(db.String(16), default='pending', nullable=False)  # pending/checked
    checked_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    checked_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('event_id','node_id', name='uq_event_node'),)

class Presence(db.Model):
    __tablename__ = 'presence'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    last_seen_at = db.Column(db.DateTime, index=True)
    device_info = db.Column(db.String(255))

class ActivityLog(db.Model):
    __tablename__ = 'activity_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    target_node_id = db.Column(db.Integer, db.ForeignKey('inventory_node.id'), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
