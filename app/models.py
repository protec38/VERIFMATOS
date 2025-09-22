from datetime import datetime
import os, secrets
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db, login_manager

ROLE_ADMIN='admin'; ROLE_CHEF='chef'; ROLE_SECOURISTE='secouriste'

class User(UserMixin, db.Model):
    __tablename__='users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default=ROLE_SECOURISTE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self,p): self.password_hash = generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)

@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def ensure_default_admin():
    u = os.getenv('ADMIN_DEFAULT_USERNAME','admin'); p = os.getenv('ADMIN_DEFAULT_PASSWORD','admin')
    x = User.query.filter_by(username=u).first()
    if not x:
        x = User(username=u, role=ROLE_ADMIN); x.set_password(p); db.session.add(x); db.session.commit()

class Item(db.Model):
    __tablename__='items'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    is_parent = db.Column(db.Boolean, default=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=True)
    expected_qty = db.Column(db.Integer, default=1)  # for children; boolean check only, quantity shown
    unique_code = db.Column(db.String(64), unique=True, nullable=True)  # to allow multiple instances of same parent
    active = db.Column(db.Boolean, default=True)
    parent = db.relationship('Item', remote_side=[id], backref='children')

class Event(db.Model):
    __tablename__='events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    location = db.Column(db.String(180), nullable=True)
    chef_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    token = db.Column(db.String(32), unique=True, default=lambda: secrets.token_hex(8))
    state = db.Column(db.String(20), default='draft')  # draft | in_progress | closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chef = db.relationship('User', backref='events')

class EventItem(db.Model):
    __tablename__='event_items'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    loaded = db.Column(db.Boolean, default=False)
    event = db.relationship('Event', backref='event_items')
    item = db.relationship('Item')

class EventChild(db.Model):
    __tablename__='event_children'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    child_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    included = db.Column(db.Boolean, default=True)
    __table_args__=(db.UniqueConstraint('event_id','child_id', name='uq_event_child'),)
    event = db.relationship('Event', backref='event_children')
    parent = db.relationship('Item', foreign_keys=[parent_id])
    child = db.relationship('Item', foreign_keys=[child_id])

class Verification(db.Model):
    __tablename__='verifications'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('items.id'), nullable=False)
    verified = db.Column(db.Boolean, default=False)
    last_by = db.Column(db.String(120))
    last_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__=(db.UniqueConstraint('event_id','item_id', name='uq_event_item'),)
    event = db.relationship('Event', backref='verifications')
    item = db.relationship('Item')

class Activity(db.Model):
    __tablename__='activities'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    actor = db.Column(db.String(120))
    action = db.Column(db.String(64))
    item_id = db.Column(db.Integer, nullable=True)
    at = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.relationship('Event', backref='activities')

class Presence(db.Model):
    __tablename__='presence'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('items.id'))
    volunteer = db.Column(db.String(120))
    ping_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__=(db.UniqueConstraint('event_id','parent_id','volunteer', name='uq_presence'),)
