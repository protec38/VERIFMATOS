# app/views_html.py — Pages HTML (Jinja)
from __future__ import annotations
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    render_template_string,
    request,
    redirect,
    url_for,
    abort,
    current_app,
)
from flask_login import login_required, current_user, logout_user

from . import db
from .models import (
    Event,
    EventStatus,
    Role,
    EventShareLink,
    StockNode,
    NodeType,
    EventTemplate,
    EventTemplateKind,
    event_stock,
    User,
)
from .tree_query import build_event_tree

bp = Blueprint("pages", __name__)

# -------------------------
# Helpers rôles
# -------------------------
def is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == Role.ADMIN

def can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (
        Role.ADMIN,
        Role.CHEF,
        Role.VIEWER,
        getattr(Role, "VERIFICATIONPERIODIQUE", Role.VIEWER),
    )

def can_manage_event() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)


def can_periodic_verify() -> bool:
    return current_user.is_authenticated and current_user.role in (
        Role.ADMIN,
        Role.CHEF,
        getattr(Role, "VERIFICATIONPERIODIQUE", Role.CHEF),
    )


def _serialize_template(tpl: EventTemplate) -> dict:
    return {
        "id": tpl.id,
        "name": tpl.name,
        "kind": getattr(tpl.kind, "name", str(tpl.kind)).upper(),
        "description": tpl.description,
        "nodes": [
            {
                "id": node.node_id,
                "quantity": node.quantity,
            }
            for node in sorted(tpl.nodes, key=lambda n: n.node_id)
        ],
    }

# -------------------------
# Auth HTML
# -------------------------
@bp.route("/login", methods=["GET"])
def login():
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

# -------------------------
# Dashboard (liste événements + création)
# -------------------------
@bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        if not can_manage_event():
            abort(403)

        name = (request.form.get("name") or "").strip()
        date_str = (request.form.get("date") or "").strip()

        root_ids = request.form.getlist("root_ids")
        try:
            root_ids = [int(r) for r in root_ids if r and str(r).isdigit()]
        except Exception:
            root_ids = []

        if not name or not root_ids:
            abort(400, description="Nom et au moins un parent racine requis")

        dt = None
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str).date()
            except Exception:
                dt = None

        ev = Event(
            name=name,
            date=dt,
            status=EventStatus.OPEN,
            created_by_id=current_user.id,
        )
        db.session.add(ev)
        db.session.flush()  # ev.id

        # Associer les parents racine sélectionnés
        added = 0
        for rid in sorted(set(root_ids)):
            root = db.session.get(StockNode, rid)
            if not root or root.type != NodeType.GROUP or root.parent_id is not None:
                continue  # on ne prend que les VRAIES racines
            db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=root.id))
            added += 1

        current_app.logger.info(
            "[DASH CREATE] ev_id=%s name=%s roots=%s added=%s",
            ev.id, ev.name, root_ids, added
        )

        if not added:
            db.session.rollback()
            abort(400, description="Aucun parent racine valide sélectionné")

        db.session.commit()
        return redirect(url_for("pages.event_page", event_id=ev.id))

    # GET: afficher la liste + les parents racine possibles
    if not can_view():
        abort(403)

    events = Event.query.order_by(Event.created_at.desc()).all()
    roots = (
        StockNode.query
        .filter(StockNode.parent_id.is_(None), StockNode.type == NodeType.GROUP)
        .order_by(StockNode.name.asc())
        .all()
    )
    templates = (
        EventTemplate.query
        .order_by(EventTemplate.kind.asc(), EventTemplate.name.asc())
        .all()
    )
    template_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.TEMPLATE]
    lot_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.LOT]
    return render_template(
        "home.html",
        events=events,
        can_manage=can_manage_event(),
        roots=roots,
        templates=template_specs,
        lots=lot_specs,
    )


@bp.get("/templates")
@login_required
def templates_manage_page():
    if not can_manage_event():
        abort(403)

    roots = (
        StockNode.query
        .filter(StockNode.parent_id.is_(None), StockNode.type == NodeType.GROUP)
        .order_by(StockNode.name.asc())
        .all()
    )
    templates = (
        EventTemplate.query
        .order_by(EventTemplate.kind.asc(), EventTemplate.name.asc())
        .all()
    )
    template_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.TEMPLATE]
    lot_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.LOT]

    root_specs = [
        {
            "id": r.id,
            "name": r.name,
            "unique_item": bool(getattr(r, "unique_item", False)),
            "unique_quantity": getattr(r, "unique_quantity", None),
        }
        for r in roots
    ]

    return render_template(
        "templates_manage.html",
        roots=root_specs,
        templates=template_specs,
        lots=lot_specs,
    )

# -------------------------
# Page Événement (interne)
# -------------------------
@bp.get("/events/<int:event_id>")
@login_required
def event_page(event_id: int):
    if not can_view():
        abort(403)
    ev = db.session.get(Event, event_id)
    if not ev:
        abort(404)
    tree = build_event_tree(event_id)
    current_app.logger.info("[EVENT PAGE] ev_id=%s tree_roots=%s", ev.id, len(tree))
    return render_template("event.html", event=ev, tree=tree)

# -------------------------
# Page publique (secouristes via lien partagé)
# -------------------------
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id)

    # ✅ Normalisation robuste du statut:
    # - si Enum => ev.status.name
    # - si string => 'OPEN'/'CLOSED'
    status_raw = getattr(ev.status, "name", ev.status)
    is_open = str(status_raw).upper() == "OPEN"

    return render_template(
        "public_event.html",
        event=ev,
        tree=tree,
        token=token,
        is_open=is_open,  # booléen toujours correct
    )

# -------------------------
# STOCK (UI) — ADMIN ONLY
# -------------------------
@bp.get("/stock")
@login_required
def stock_page():
    if not is_admin():
        abort(403)
    return render_template("manage.html", active_tab="stock")

# -------------------------
# ADMIN (UI Utilisateurs) — ADMIN ONLY
# -------------------------
@bp.route("/admin", methods=["GET", "POST"])
@login_required
def admin_page():
    if not is_admin():
        abort(403)

    if request.method == "POST":
        action = request.form.get("action") or ""

        if action == "create_user":
            username = (request.form.get("username") or "").strip()
            password = (request.form.get("password") or "").strip()
            role_name = (request.form.get("role") or "VIEWER").strip().upper()
            if not username or not password:
                abort(400, description="username et password requis")
            try:
                role = Role[role_name]
            except KeyError:
                role = Role.VIEWER
            if User.query.filter_by(username=username).first():
                abort(400, description="Nom d’utilisateur déjà pris")
            u = User(username=username, role=role, is_active=True)
            try:
                u.set_password(password)
            except Exception:
                from werkzeug.security import generate_password_hash
                u.password_hash = generate_password_hash(password)
            db.session.add(u)
            db.session.commit()
            return redirect(url_for("pages.admin_page"))

        if action == "reset_password":
            user_id = request.form.get("user_id")
            new_pwd = (request.form.get("new_password") or "").strip()
            if not user_id or not new_pwd:
                abort(400, description="user_id et new_password requis")
            u = db.session.get(User, int(user_id))
            if not u:
                abort(404)
            try:
                u.set_password(new_pwd)
            except Exception:
                from werkzeug.security import generate_password_hash
                u.password_hash = generate_password_hash(new_pwd)
            db.session.commit()
            return redirect(url_for("pages.admin_page"))

        if action == "toggle_active":
            user_id = request.form.get("user_id")
            if not user_id:
                abort(400)
            u = db.session.get(User, int(user_id))
            if not u:
                abort(404)
            if u.id == current_user.id:
                abort(400, description="Impossible de se désactiver soi-même")
            u.is_active = not bool(u.is_active)
            db.session.commit()
            return redirect(url_for("pages.admin_page"))

        if action == "delete_user":
            user_id = request.form.get("user_id")
            if not user_id:
                abort(400)
            u = db.session.get(User, int(user_id))
            if not u:
                abort(404)
            if u.id == current_user.id:
                abort(400, description="Impossible de se supprimer soi-même")
            db.session.delete(u)
            db.session.commit()
            return redirect(url_for("pages.admin_page"))

        abort(400, description="Action inconnue")

    users = User.query.order_by(User.username.asc()).all()
    return render_template("admin.html", users=users, Role=Role)

# -------------------------
# Page Péremptions
# -------------------------
@bp.get("/peremption")
@login_required
def peremption_page():
    if not can_view():
        abort(403)
    return render_template("peremption.html")


@bp.get("/verification-periodique")
@login_required
def verification_periodique_page():
    if not can_periodic_verify():
        abort(403)

    roots = (
        StockNode.query
        .filter(StockNode.parent_id.is_(None))
        .order_by(StockNode.name.asc())
        .all()
    )
    root_payload = [
        {
            "id": root.id,
            "name": root.name,
        }
        for root in roots
    ]
    return render_template("verification_periodique.html", roots=root_payload)
