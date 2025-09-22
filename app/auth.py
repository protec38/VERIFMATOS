from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .models import User, ROLE_ADMIN, db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username'); password=request.form.get('password')
        u=User.query.filter_by(username=username).first()
        if u and u.check_password(password):
            login_user(u); return redirect(url_for('index'))
        flash('Identifiants invalides','danger')
    return render_template('auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('auth.login'))

@auth_bp.route('/admin/users')
@login_required
def users():
    if current_user.role!=ROLE_ADMIN: return redirect(url_for('index'))
    users=User.query.all()
    return render_template('admin/users.html', users=users)

@auth_bp.route('/admin/users/create', methods=['POST'])
@login_required
def create_user():
    if current_user.role!=ROLE_ADMIN: return redirect(url_for('index'))
    username=request.form.get('username'); password=request.form.get('password') or 'changeme'
    role=request.form.get('role') or 'chef'
    if not username: flash("Nom d'utilisateur requis",'danger'); return redirect(url_for('auth.users'))
    if User.query.filter_by(username=username).first(): flash("Nom d'utilisateur déjà pris",'warning'); return redirect(url_for('auth.users'))
    u=User(username=username, role=role); u.set_password(password); db.session.add(u); db.session.commit()
    flash('Utilisateur créé','success'); return redirect(url_for('auth.users'))

@auth_bp.route('/admin/users/<int:uid>/delete', methods=['POST'])
@login_required
def delete_user(uid):
    if current_user.role!=ROLE_ADMIN: return redirect(url_for('index'))
    if current_user.id==uid: flash("Impossible de supprimer votre propre compte",'warning'); return redirect(url_for('auth.users'))
    u=User.query.get(uid)
    if u: db.session.delete(u); db.session.commit(); flash('Utilisateur supprimé','success')
    return redirect(url_for('auth.users'))
