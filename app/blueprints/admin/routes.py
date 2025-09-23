
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import User
from app.guards import roles_required
from werkzeug.security import generate_password_hash

bp = Blueprint('admin', __name__)

@bp.get('/users')
@roles_required('admin')
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([{'id': u.id, 'email': u.email, 'display_name': u.display_name, 'role': u.role, 'active': u.is_active} for u in users])

@bp.post('/users')
@roles_required('admin')
def create_user():
    data = request.get_json() or {}
    u = User(
        email=data.get('email'),
        password_hash=generate_password_hash(data.get('password','changeme')),
        display_name=data.get('display_name') or data.get('email'),
        role=data.get('role','viewer'),
        is_active=True
    )
    db.session.add(u)
    db.session.commit()
    return jsonify(id=u.id), 201

@bp.patch('/users/<int:user_id>')
@roles_required('admin')
def update_user(user_id):
    u = User.query.get_or_404(user_id)
    data = request.get_json() or {}
    for k in ['email','display_name','role','is_active']:
        if k in data:
            setattr(u, k, data[k])
    if 'password' in data and data['password']:
        from werkzeug.security import generate_password_hash
        u.password_hash = generate_password_hash(data['password'])
    db.session.commit()
    return jsonify(message='ok')

@bp.delete('/users/<int:user_id>')
@roles_required('admin')
def delete_user(user_id):
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    return jsonify(message='deleted')
