# app/views_html.py — Pages HTML (Jinja) : login/logout, dashboard, event, public
from __future__ import annotations
from datetime import datetime
from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user, login_user, logout_user
from . import db
from .models import Event, EventStatus, Role, StockNode, NodeType, event_stock, EventShareLink, User
from .tree_query import build_event_tree

bp = Blueprint("pages", __name__)

def can_view():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

def can_manage():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

# -------- Auth HTML --------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password) or not user.is_active:
            return render_template_string(
                '{% extends "base.html" %}{% block content %}'
                '<div class="card"><div class="title">Connexion</div><p class="muted">Identifiants invalides.</p>'
                '<form method="post" class="row" style="margin-top:10px;">'
                '<input name="username" placeholder="Nom d’utilisateur">'
                '<input name="password" type="password" placeholder="Mot de passe">'
                '<button class="btn primary" type="submit">Se connecter</button>'
                '</form></div>{% endblock %}'
            )
        login_user(user)
        return redirect(url_for("pages.dashboard"))
    # GET
    return render_template_string(
        '{% extends "base.html" %}{% block content %}'
        '<div class="card"><div class="title">Connexion</div>'
        '<form method="post" class="row" style="margin-top:10px;">'
        '<input name="username" placeholder="Nom d’utilisateur">'
        '<input name="password" type="password" placeholder="Mot de passe">'
        '<button class="btn primary" type="submit">Se connecter</button>'
        '</form></div>{% endblock %}'
    )

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("pages.login"))

# -------- Dashboard --------

@bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        if not can_manage():
            abort(403)
        name = (request.form.get("name") or "").strip()
        date_str = (request.form.get("date") or "").strip()
        if not name:
            abort(400)
        date = None
        if date_str:
            try:
                date = datetime.fromisoformat(date_str).date()
            except Exception:
                date = None
        ev = Event(name=name, date=date, status=EventStatus.OPEN, created_by_id=current_user.id)
        db.session.add(ev)
        db.session.commit()
        return redirect(url_for("pages.event_page", event_id=ev.id))

    if not can_view():
        abort(403)
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template("home.html", events=events, can_manage=can_manage())

# -------- Pages Événement / Public --------

@bp.get("/events/<int:event_id>")
@login_required
def event_page(event_id: int):
    if not can_view():
        abort(403)
    ev = db.session.get(Event, event_id)
    if not ev:
        abort(404)
    tree = build_event_tree(event_id)
    return render_template("event.html", event=ev, tree=tree)

@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id)
    return render_template("public_event.html", event=ev, tree=tree, token=token)
