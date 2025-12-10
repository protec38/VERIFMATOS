# app/views_html.py — Pages HTML (Jinja)
from __future__ import annotations
from datetime import datetime, date

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
    PeriodicVerificationSession,
    PeriodicVerificationRecord,
    ItemStatus,
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
    next_url = (request.args.get("next") or "").strip()
    return render_template("login.html", error=error, next_url=next_url)

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

    search_query = (request.args.get("q") or "").strip()

    events_query = Event.query
    if search_query:
        events_query = events_query.filter(Event.name.ilike(f"%{search_query}%"))

    events = events_query.all()

    today = date.today()

    def _event_sort_key(ev: Event) -> tuple:
        created_sort = -ev.created_at.timestamp() if ev.created_at else 0
        if ev.date is None:
            return (2, float("inf"), date.max, created_sort)

        delta_days = (ev.date - today).days
        priority = 0 if delta_days >= 0 else 1
        return (priority, abs(delta_days), ev.date, created_sort)

    events.sort(key=_event_sort_key)
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
        search_query=search_query,
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
    slot_groups = []
    grouped = {}
    try:
        slots_iter = sorted(
            getattr(ev, "material_slots", []) or [],
            key=lambda s: (getattr(s, "start_at", datetime.min), getattr(s, "node_id", 0)),
        )
    except Exception:
        slots_iter = []

    for slot in slots_iter:
        start_at = getattr(slot, "start_at", None)
        end_at = getattr(slot, "end_at", None)
        if not start_at or not end_at:
            continue
        key = (start_at, end_at)
        group = grouped.get(key)
        if not group:
            group = {
                "start": start_at,
                "end": end_at,
                "nodes": [],
            }
            grouped[key] = group
            slot_groups.append(group)
        node = getattr(slot, "node", None)
        node_name = getattr(node, "name", None) or f"Objet #{getattr(slot, 'node_id', '?')}"
        group["nodes"].append(node_name)

    for group in slot_groups:
        try:
            group["nodes"].sort(key=lambda x: x.lower())
        except Exception:
            group["nodes"] = sorted(group["nodes"])

    slot_payload = [
        {
            "start": group["start"].isoformat(),
            "end": group["end"].isoformat(),
            "nodes": list(group["nodes"]),
        }
        for group in slot_groups
    ]

    return render_template(
        "event.html",
        event=ev,
        tree=tree,
        event_status=status_txt,
        allow_verify=allow_verify,
        can_manage=can_manage_event(),
        material_slots=slot_groups,
        material_slots_payload=slot_payload,
    )


@bp.get("/calendar")
@login_required
def calendar_page():
    if not can_view():
        abort(403)

    roots = list_roots()
    nodes_payload = [
        {
            "id": node.id,
            "name": node.name,
        }
        for node in roots
    ]

    return render_template(
        "calendar.html",
        nodes=nodes_payload,
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

    try:
        PeriodicVerificationSession.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

    recent_sessions = (
        PeriodicVerificationSession.query
        .order_by(PeriodicVerificationSession.created_at.desc())
        .limit(8)
        .all()
    )

    recent_verifications = []
    for session in recent_sessions:
        timestamp = session.created_at
        display_name = (
            session.verifier_name
            or (
                f"{(session.verifier_first_name or '').strip()} {(session.verifier_last_name or '').strip()}".strip()
            )
            or getattr(getattr(session, "verifier", None), "username", None)
            or None
        )
        if display_name:
            display_name = " ".join(display_name.split())
        source = (session.source or "internal").lower()
        source_label = "Lien public" if source.startswith("public") else "Interne"
        missing_count = getattr(session, "missing_count", 0) or 0
        recent_verifications.append(
            {
                "id": session.id,
                "verifier": display_name or "Inconnu",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "source": source,
                "source_label": source_label,
                "comment": session.comment,
                "root_name": getattr(getattr(session, "root", None), "name", None) or "Parent non trouvé",
                "missing_count": missing_count,
            }
        )

    return render_template(
        "admin.html",
        users=users,
        Role=Role,
        recent_verifications=recent_verifications,
    )


def _resolve_root_name(node: StockNode | None) -> str | None:
    current = node
    guard = 0
    while current is not None and current.parent_id is not None and guard < 50:
        current = current.parent
        guard += 1
    return getattr(current, "name", None)


@bp.get("/suivi-verifications")
@login_required
def verification_admin_view():
    if not is_admin():
        abort(403)

    try:
        PeriodicVerificationSession.__table__.create(bind=db.engine, checkfirst=True)
        PeriodicVerificationRecord.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

    sessions = (
        PeriodicVerificationSession.query
        .order_by(PeriodicVerificationSession.created_at.desc())
        .limit(20)
        .all()
    )

    session_feed = []
    for session in sessions:
        timestamp = session.created_at
        display_name = (
            session.verifier_name
            or (
                f"{(session.verifier_first_name or '').strip()} {(session.verifier_last_name or '').strip()}".strip()
            )
            or getattr(getattr(session, "verifier", None), "username", None)
            or None
        )
        if display_name:
            display_name = " ".join(display_name.split())
        source = (session.source or "internal").lower()
        source_label = "Lien public" if source.startswith("public") else "Interne"
        session_feed.append(
            {
                "id": session.id,
                "verifier": display_name or "Inconnu",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "source_label": source_label,
                "comment": session.comment,
                "root_name": getattr(getattr(session, "root", None), "name", None) or "Parent non trouvé",
                "missing_count": getattr(session, "missing_count", 0) or 0,
            }
        )

    missing_records = (
        PeriodicVerificationRecord.query
        .filter(PeriodicVerificationRecord.status == ItemStatus.NOT_OK)
        .order_by(PeriodicVerificationRecord.created_at.desc())
        .limit(30)
        .all()
    )

    missing_payload = []
    for rec in missing_records:
        node = getattr(rec, "node", None)
        missing_payload.append(
            {
                "id": rec.id,
                "item_name": getattr(node, "name", None) or f"Item #{rec.node_id}",
                "root_name": _resolve_root_name(node) or "Parent inconnu",
                "missing_qty": rec.missing_qty,
                "comment": rec.comment,
                "issue": getattr(rec.issue_code, "name", None),
                "verifier": rec.verifier_name or getattr(getattr(rec, "verifier", None), "username", None) or "Inconnu",
                "created_at": rec.created_at.isoformat() if rec.created_at else None,
            }
        )

    return render_template(
        "verification_admin.html",
        sessions=session_feed,
        missing_items=missing_payload,
    )


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

@bp.get("/verification-periodique")
def verification_periodique_page():
    return redirect(url_for("verification_periodique.public_catalog"))


@bp.get("/verification-publique")
def verification_publique():
    """Alias lisible et accessible sans connexion vers la vérification publique."""
    return redirect(url_for("verification_periodique.public_catalog"))
