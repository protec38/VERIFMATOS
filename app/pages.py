
from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user

bp = Blueprint('pages', __name__)

@bp.get('/')
@login_required
def index():
    return render_template('dashboard.html')

@bp.get('/login')
def login():
    # SPA-style login form posts to /auth/login via JS
    if current_user.is_authenticated:
        return redirect(url_for('pages.index'))
    return render_template('auth/login.html')

@bp.get('/inventory/ui')
@login_required
def inventory_ui():
    return render_template('inventory/index.html')

@bp.get('/events/ui')
@login_required
def events_ui():
    return render_template('events/detail.html')

@bp.get('/admin/users/ui')
@login_required
def admin_users_ui():
    return render_template('admin/users.html')

@bp.get('/public')
def public_ui():
    # This template fetches /p/<token> via JS with ?t=... query param
    return render_template('public/view.html')
