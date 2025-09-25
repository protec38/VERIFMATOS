# app/auth/views.py — Authentification (JSON)
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from ..models import User

bp = Blueprint("auth", __name__)

@bp.post("/login")
def login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify(error="username and password required"), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify(error="Bad credentials"), 401
    if not user.is_active:
        return jsonify(error="User disabled"), 403
    login_user(user)
    return jsonify(ok=True, username=user.username, role=user.role.name)

@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify(ok=True)

@bp.get("/me")
@login_required
def me():
    u = current_user
    return jsonify(id=u.id, username=u.username, role=u.role.name, is_active=u.is_active)
