# app/views_html.py — Pages HTML (Jinja)
from __future__ import annotations
from datetime import datetime
import secrets

from flask import (
    Blueprint,
    render_template,
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
    StockRootCategory,
    NodeType,
    EventTemplate,
    EventTemplateKind,
    event_stock,
    User,
    AuditLog,
    PeriodicVerificationLink,
)
from .tree_query import build_event_tree
from .stock.service import list_roots

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


def _root_payload(node: StockNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "unique_item": bool(getattr(node, "unique_item", False)),
        "unique_quantity": getattr(node, "unique_quantity", None),
        "root_category_id": getattr(node, "root_category_id", None),
    }

# -------------------------
# Auth HTML
# -------------------------
@bp.route("/login", methods=["GET"])
def login():
    error = (request.args.get("error") or "").strip()
    return render_template("login.html", error=error)

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
    roots = list_roots()
    categories = (
        StockRootCategory.query
        .order_by(StockRootCategory.position.asc(), StockRootCategory.name.asc())
        .all()
    )
    root_specs = [_root_payload(r) for r in roots]
    grouped_roots = []
    used_root_ids: set[int] = set()
    for cat in categories:
        nodes = [payload for payload in root_specs if payload["root_category_id"] == cat.id]
        grouped_roots.append(
            {
                "category": {"id": cat.id, "name": cat.name},
                "nodes": nodes,
            }
        )
        used_root_ids.update(node["id"] for node in nodes)
    remaining = [payload for payload in root_specs if payload["id"] not in used_root_ids]
    if remaining:
        grouped_roots.append({"category": None, "nodes": remaining})
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
        root_groups=grouped_roots,
        roots_flat=root_specs,
        templates=template_specs,
        lots=lot_specs,
    )


@bp.get("/templates")
@login_required
def templates_manage_page():
    if not can_manage_event():
        abort(403)

    roots = list_roots()
    categories = (
        StockRootCategory.query
        .order_by(StockRootCategory.position.asc(), StockRootCategory.name.asc())
        .all()
    )
    templates = (
        EventTemplate.query
        .order_by(EventTemplate.kind.asc(), EventTemplate.name.asc())
        .all()
    )
    template_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.TEMPLATE]
    lot_specs = [_serialize_template(t) for t in templates if t.kind == EventTemplateKind.LOT]

    root_specs = [_root_payload(r) for r in roots]
    grouped_roots = []
    used_root_ids: set[int] = set()
    for cat in categories:
        nodes = [payload for payload in root_specs if payload["root_category_id"] == cat.id]
        grouped_roots.append(
            {
                "category": {"id": cat.id, "name": cat.name},
                "nodes": nodes,
            }
        )
        used_root_ids.update(node["id"] for node in nodes)
    remaining = [payload for payload in root_specs if payload["id"] not in used_root_ids]
    if remaining:
        grouped_roots.append({"category": None, "nodes": remaining})

    return render_template(
        "templates_manage.html",
        root_groups=grouped_roots,
        roots_flat=root_specs,
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
    status_raw = getattr(ev.status, "name", ev.status)
    status_txt = str(status_raw).upper()
    allow_verify = current_user.is_authenticated and current_user.role == Role.ADMIN
    return render_template(
        "event.html",
        event=ev,
        tree=tree,
        event_status=status_txt,
        allow_verify=allow_verify,
        can_manage=can_manage_event(),
    )

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


@bp.get("/admin/logins")
@login_required
def admin_login_logs():
    if not is_admin():
        abort(403)

    try:
        AuditLog.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

    logs = (
        AuditLog.query
        .filter(AuditLog.action.in_(["login.success", "login.failure"]))
        .order_by(AuditLog.ts.desc())
        .limit(200)
        .all()
    )
    return render_template("admin_login_logs.html", logs=logs)

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

    try:
        PeriodicVerificationLink.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

    def _generate_link_token() -> str | None:
        for _ in range(10):
            token = secrets.token_urlsafe(16)
            if not PeriodicVerificationLink.query.filter_by(token=token).first():
                return token
        return None

    created_links = False
    for root in roots:
        existing = (
            PeriodicVerificationLink.query
            .filter_by(root_id=root.id, active=True)
            .order_by(PeriodicVerificationLink.created_at.desc())
            .first()
        )
        if existing:
            continue
        token = _generate_link_token()
        if not token:
            current_app.logger.warning(
                "Impossible de générer un lien public pour le parent %s", root.id
            )
            continue
        link = PeriodicVerificationLink(
            token=token,
            root_id=root.id,
            active=True,
            created_by_id=getattr(current_user, "id", None),
        )
        db.session.add(link)
        created_links = True

    if created_links:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.warning(
                "Impossible d'enregistrer automatiquement les liens publics : %s", exc
            )

    root_payload = [
        {
            "id": root.id,
            "name": root.name,
        }
        for root in roots
    ]
    current_user_name = getattr(current_user, "username", None)
    return render_template(
        "verification_periodique.html",
        roots=root_payload,
        current_user_name=current_user_name,
    )
