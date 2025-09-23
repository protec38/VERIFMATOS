from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from ...models import User, Role
from ...extensions import db

bp = Blueprint('admin', __name__)

def require_admin():
    return current_user.is_authenticated and current_user.role == Role.ADMIN

@bp.get('/users')
@login_required
def users():
    if not require_admin():
        flash("Accès refusé", "danger")
        return redirect(url_for('core.index'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users, Role=Role)

@bp.post('/users')
@login_required
def create_user():
    if not require_admin():
        flash("Accès refusé", "danger")
        return redirect(url_for('core.index'))
    email = request.form['email'].strip().lower()
    display = request.form.get('display_name') or email.split('@')[0]
    role = request.form.get('role', Role.VIEWER)
    pwd = request.form.get('password', 'changeme')
    u = User(email=email, display_name=display, role=role, password_hash=generate_password_hash(pwd))
    db.session.add(u); db.session.commit()
    flash("Utilisateur créé", "success")
    return redirect(url_for('admin.users'))
