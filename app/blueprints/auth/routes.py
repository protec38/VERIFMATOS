
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from app.extensions import db
from app.models import User

bp = Blueprint('auth', __name__)

@bp.post('/login')
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify(error='email and password required'), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(error='invalid credentials'), 401
    if not user.is_active:
        return jsonify(error='user disabled'), 403
    login_user(user)
    return jsonify(message='ok', user={'id': user.id, 'email': user.email, 'role': user.role})

@bp.post('/logout')
def logout():
    if current_user.is_authenticated:
        logout_user()
    return jsonify(message='ok')

@bp.get('/whoami')
def whoami():
    if not current_user.is_authenticated:
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, id=current_user.id, email=current_user.email, role=current_user.role)
