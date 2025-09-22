from datetime import datetime
import os, secrets
from . import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

ROLE_ADMIN = 'admin'
ROLE_CHEF = 'chef'
ROLE_SECOURISTE = 'secouriste'

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_SECOURISTE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def ensure_default_admin():
    username = os.getenv('ADMIN_DEFAULT_USERNAME', 'admin')
    password = os.getenv('ADMIN_DEFAULT_PASSWORD', 'admin')
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username, role=ROLE_ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

class Item(db.Model):
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    is_parent = db.Column(db.Boolean, default=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=True)
    unique_code = db.Column(db.String(64), unique=True, nullable=True)
    active = db.Column(db.Boolean, default=True)

    parent = db.relationship('Item', remote_side=[id], backref='children')

class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(180), nullable=True)
    chef_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    token = db.Column(db.String(32), unique=True, default=lambda: secrets.token_hex(8))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    chef = db.relationship('User', backref='events')

class EventItem(db.Model):
    __tablename__ = 'event_items'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    loaded = db.Column(db.Boolean, default=False)

    event = db.relationship('Event', backref='event_items')
    item = db.relationship('Item')

class Verification(db.Model):
    __tablename__ = 'verifications'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    verified_by = db.Column(db.String(120), nullable=False)
    verified_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(255), nullable=True)

    event = db.relationship('Event', backref='verifications')
    item = db.relationship('Item')
