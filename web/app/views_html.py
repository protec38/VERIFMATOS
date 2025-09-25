# app/views_html.py — Pages HTML (Jinja): Admin-only Stock/Admin; création d’événement multi-parents; page événement avec TREE injecté
from __future__ import annotations
from datetime import datetime
from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, abort
from flask_login import login_required, current_user, logout_user
from . import db
from .models import (
    Event,
    EventStatus,
    Role,
    EventShareLink,
    StockNode,
    NodeType,
    event_stock,
)
from .tree_query import build_event_tree

bp = Blueprint("pages", __name__)

def is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == Role.ADMIN

def can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

def can_manage_event() -> bool:
    # Création d'événements autorisée pour ADMIN et CHEF
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

# -------- Auth HTML --------
@bp.route("/login", methods=["GET"])
def login():
    # Le POST /login est géré par app/auth/views.py (JSON ou form)
    return render_template_string(
        '{% extends "base.html" %}{% block content %}'
        '<div class="card"><div class="title">Connexion</div>'
        '<form method="post" action="/login" class="row" style="margin-top:10px;">'
        '<input name="username" placeholder="Nom d’utilisateur" required>'
        '<input name="password" type="password" placeholder="Mot de passe" required>'
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
        if not can_manage_event():
            abort(403)
        name = (request.form.get("name") or "").strip()
        date_str = (request.form.get("date") or "").strip()
        # Multi-sélection de parents
        root_ids = request.form.getlist("root_ids")
        try:
            root_ids = [int(r) for r in root_ids if r and str(r).isdigit()]
        except Exception:
            root_ids = []
        if not name or not root_ids:
            abort(400, description="Nom requis et au moins un parent racine")

        date = None
        if date_str:
            try:
                date = datetime.fromisoformat(date_str).date()
            except Exception:
                date = None

        ev = Event(name=name, date=date, status=EventStatus.OPEN, created_by_id=current_user.id)
        db.session.add(ev)
        db.session.flush()

        # Associer tous les parents sélectionnés (parents racine uniquement)
        added = 0
        for rid in sorted(set(root_ids)):
            root = db.session.get(StockNode, rid)
            if not root or root.type != NodeType.GROUP or root.level != 0:
                continue  # ignore si non valide
            db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=root.id))
            added += 1
        if not added:
            db.session.rollback()
            abort(400, description="Aucun parent racine valide sélectionné")

        db.session.commit()
        return redirect(url_for("pages.event_page", event_id=ev.id))

    if not can_view():
        abort(403)

    events = Event.query.order_by(Event.created_at.desc()).all()
    # Parents racine disponibles pour l’association
    roots = (
        StockNode.query
        .filter(StockNode.level == 0, StockNode.type == NodeType.GROUP)
        .order_by(StockNode.name.asc())
        .all()
    )
    return render_template("home.html", events=events, can_manage=can_manage_event(), roots=roots)

# -------- Page Événement --------
@bp.get("/events/<int:event_id>")
@login_required
def event_page(event_id: int):
    if not can_view():
        abort(403)
    ev = db.session.get(Event, event_id)
    if not ev:
        abort(404)
    # Construit l’arbre complet lié à l’événement (inclut les parents associés, leurs enfants, etc.)
    tree = build_event_tree(event_id)  # <- IMPORTANT: injecté au template
    return render_template("event.html", event=ev, tree=tree)

# -------- Page publique (secouristes via lien partagé) --------
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id)
    return render_template("public_event.html", event=ev, tree=tree, token=token)

# -------- Gestion Stock (UI) — ADMIN ONLY --------
@bp.get("/stock")
@login_required
def stock_page():
    if not is_admin():
        abort(403)
    return render_template("manage.html", active_tab="stock")

# -------- Gestion Admin (UI) — ADMIN ONLY --------
@bp.get("/admin")
@login_required
def admin_page():
    if not is_admin():
        abort(403)
    return render_template("manage.html", active_tab="admin")
