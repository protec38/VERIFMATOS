# app/admin/views.py — Gestion utilisateurs (ADMIN)
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from .. import db
from ..models import User, Role

bp = Blueprint("admin", __name__)

def require_admin():
    return current_user.is_authenticated and current_user.role == Role.ADMIN

@bp.get("/admin/users")
@login_required
def list_users():
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    users = User.query.order_by(User.id).all()
    return jsonify([{"id":u.id,"username":u.username,"role":u.role.name,"is_active":u.is_active} for u in users])

@bp.post("/admin/users")
@login_required
def create_user():
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password", "changeme")
    role_str = (data.get("role","CHEF") or "CHEF").upper()
    if not username:
        return jsonify(error="username required"), 400
    if User.query.filter_by(username=username).first():
        return jsonify(error="username exists"), 409
    try:
        role = Role[role_str]
    except KeyError:
        return jsonify(error="invalid role"), 400
    u = User(username=username, role=role, is_active=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return jsonify(id=u.id, username=u.username, role=u.role.name)

@bp.patch("/admin/users/<int:user_id>")
@login_required
def update_user(user_id:int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    u = db.session.get(User, user_id)
    if not u:
        return jsonify(error="Not found"), 404
    data = request.get_json() or {}
    if "role" in data:
        role_str = (data.get("role") or "").upper()
        if role_str:
            try:
                u.role = Role[role_str]
            except KeyError:
                return jsonify(error="invalid role"), 400
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    db.session.commit()
    return jsonify(id=u.id, username=u.username, role=u.role.name, is_active=u.is_active)

@bp.post("/admin/users/<int:user_id>/reset_password")
@login_required
def reset_password(user_id:int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    u = db.session.get(User, user_id)
    if not u:
        return jsonify(error="Not found"), 404
    data = request.get_json() or {}
    newpass = data.get("password", "changeme")
    u.set_password(newpass)
    db.session.commit()
    return jsonify(ok=True)
