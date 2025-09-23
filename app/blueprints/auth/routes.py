from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash
from ...models import User
from ...extensions import db

bp = Blueprint('auth', __name__)

@bp.get('/login')
def login_form():
    return render_template('auth/login.html')

@bp.post('/login')
def login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        flash('Identifiants invalides', 'danger')
        return redirect(url_for('auth.login_form'))

    login_user(user)
    user.last_login_at = db.func.now()
    db.session.commit()
    flash('Bienvenue !', 'success')
    return redirect(url_for('core.index'))

@bp.get('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnecté.', 'info')
    return redirect(url_for('auth.login_form'))
