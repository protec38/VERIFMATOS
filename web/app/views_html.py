from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, render_template, redirect, url_for,
    request, abort, flash
)
from flask_login import login_required, login_user, logout_user, current_user

from . import db
from .models import (
    User, Role,
    Event, EventStatus,
    StockNode, NodeType,
    EventShareLink,
)
from .tree_query import build_event_tree

bp = Blueprint("pages", __name__)

# -----------------------------------------------------
# Helpers droits
# -----------------------------------------------------
def _require_can_view_event(ev: Event) -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)

# -----------------------------------------------------
# Routes "simples"
# -----------------------------------------------------
@bp.get("/")
def index():
    """Redirige la racine vers le tableau de bord."""
    return redirect(url_for("pages.dashboard"))

@bp.get("/_health")
def health():
    return {"ok": True, "at": datetime.utcnow().isoformat() + "Z"}

# -----------------------------------------------------
# Authentification minimale
# -----------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "")
        user: Optional[User] = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            nxt = request.args.get("next") or url_for("pages.dashboard")
            return redirect(nxt)
        flash("Identifiants invalides", "error")
    return render_template("login.html")

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("pages.login"))

# -----------------------------------------------------
# Tableau de bord
# -----------------------------------------------------
@bp.get("/dashboard")
@login_required
def dashboard():
    # Derniers événements
    events = Event.query.order_by(Event.id.desc()).limit(50).all()

    # Parents racines (GROUP level=0) pour la création d’événement
    roots = (
        db.session.query(StockNode)
        .filter(StockNode.type == NodeType.GROUP, StockNode.level == 0)
        .order_by(StockNode.name.asc())
        .all()
    )

    return render_template("home.html", events=events, roots=roots)

# -----------------------------------------------------
# Page événement interne (chef/admin/viewer)
# -----------------------------------------------------
@bp.get("/event/<int:event_id>")
@login_required
def event_page(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)

    tree = build_event_tree(event_id)
    return render_template("event.html", event=ev, tree=tree)

# -----------------------------------------------------
# Page publique (secouristes via lien)
# -----------------------------------------------------
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first() or abort(404)
    ev = db.session.get(Event, link.event_id) or abort(404)
    if ev.status != EventStatus.OPEN:
        # Lien public inutilisable si l'évènement est fermé
        abort(403)

    tree = build_event_tree(ev.id)
    # le template public a besoin de: event, token, tree
    return render_template("public_event.html", event=ev, token=token, tree=tree)
