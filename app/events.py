import uuid
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user

from . import db
from .models import (
    Event, Item, EventParent, EventChild, EventLoad, EventPresence, EventLog,
    ROLE_ADMIN, ROLE_CHEF,
)

events_bp = Blueprint("events", __name__, template_folder="templates")

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _is_admin_or_chef() -> bool:
    try:
        return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_CHEF)
    except Exception:
        return False

def _gen_token():
    return uuid.uuid4().hex

def _event_status_payload(ev: Event):
    """Structure consommée par static/js/live.js → applyStatus()."""
    # verifications
    verifs = {}
    for ec in EventChild.query.filter_by(event_id=ev.id, included=True).all():
        verifs[str(ec.child_id)] = {
            "verified": bool(ec.verified),
            "by": ec.verified_by or "",
            "at": ec.verified_at.isoformat() if ec.verified_at else None,
        }

    # parents_complete: un parent est complet si toutes ses feuilles incluses sont verified=True
    parents_complete = {}
    for ep in EventParent.query.filter_by(event_id=ev.id).all():
        # toutes les feuilles inclues sous ce parent
        # on récupère les items leaf sous parent via la table EventChild
        child_ids = [
            ec.child_id
            for ec in EventChild.query.filter_by(event_id=ev.id, included=True).all()
            if _is_descendant_of(ec.child_id, ep.parent_id)
        ]
        if not child_ids:
            parents_complete[ep.parent_id] = False
            continue
        # verified ?
        ok = all(verifs.get(str(cid), {}).get("verified", False) for cid in child_ids)
        parents_complete[ep.parent_id] = ok

    # loaded
    loaded = {el.parent_id: bool(el.loaded) for el in EventLoad.query.filter_by(event_id=ev.id).all()}

    # busy (présence)
    busy = {}
    for p in EventPresence.query.filter_by(event_id=ev.id).all():
        if p.parent_id not in busy:
            busy[p.parent_id] = []
        # garder seulement actifs < 2 minutes
        if p.last_seen and (datetime.utcnow() - p.last_seen) <= timedelta(minutes=2):
            busy[p.parent_id].append(p.actor)

    return {
        "verifications": verifs,
        "parents_complete": parents_complete,
        "loaded": loaded,
        "busy": busy,
    }

def _is_descendant_of(child_item_id: int, parent_item_id: int) -> bool:
    """Retourne True si child_item est sous parent_item dans l’arborescence Items."""
    item = Item.query.get(child_item_id)
    while item and item.parent_id:
        if item.parent_id == parent_item_id:
            return True
        item = Item.query.get(item.parent_id)
    return False

# ---------------------------------------------------------------------
# Pages ADMIN / CHEF
# ---------------------------------------------------------------------
@events_bp.route("/")
@login_required
def list_events():
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template("events/list.html", events=events)

@events_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_event():
    if request.method == "POST":
        title = request.form.get("title") or "Nouvel événement"
        location = request.form.get("location") or ""
        date_str = request.form.get("date") or ""
        try:
            when = datetime.fromisoformat(date_str) if date_str else datetime.utcnow()
        except Exception:
            when = datetime.utcnow()

        ev = Event(title=title, location=location, date=when, state="planning", token=_gen_token())
        db.session.add(ev)
        db.session.commit()

        # log
        db.session.add(EventLog(event_id=ev.id, actor=current_user.username, action="create_event"))
        db.session.commit()

        flash("Événement créé.", "success")
        return redirect(url_for("events.view_event", event_id=ev.id))
    return render_template("events/create.html")

@events_bp.route("/<int:event_id>")
@login_required
def view_event(event_id: int):
    ev = Event.query.get_or_404(event_id)

    # Items parents associés
    parents = (
        db.session.query(Item)
        .join(EventParent, EventParent.parent_id == Item.id)
        .filter(EventParent.event_id == ev.id)
        .order_by(Item.name.asc())
        .all()
    )

    # Feuilles (EventChild) incluses pour cet event
    children = (
        db.session.query(EventChild)
        .filter_by(event_id=ev.id, included=True)
        .all()
    )
    # set pour lookup rapide
    included_child_ids = {c.child_id for c in children}

    # Chargements
    loads = {row.parent_id: row.loaded for row in EventLoad.query.filter_by(event_id=ev.id).all()}

    # lien partage
    share_link = request.url_root.rstrip("/") + url_for("events.token_access", token=ev.token)

    return render_template(
        "events/detail.html",
        ev=ev,
        parents=parents,
        included_child_ids=included_child_ids,
        loads=loads,
        share_link=share_link,
    )

# ---------------------------------------------------------------------
# Page SECouriste via lien partagé
# ---------------------------------------------------------------------
@events_bp.route("/t/<token>", methods=["GET", "POST"])
def token_access(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()

    # identification légère: nom/prénom
    actor = (request.cookies.get("actor") or "").strip()
    if request.method == "POST":
        actor = (request.form.get("actor") or "").strip()
        if not actor or len(actor) < 2:
            flash("Nom prénom requis.", "danger")
        else:
            resp = redirect(url_for("events.token_access", token=token))
            # cookie 2 jours
            resp.set_cookie("actor", actor, max_age=2 * 24 * 3600, httponly=False, samesite="Lax")
            return resp

    # parents
    parents = (
        db.session.query(Item)
        .join(EventParent, EventParent.parent_id == Item.id)
        .filter(EventParent.event_id == ev.id)
        .order_by(Item.name.asc())
        .all()
    )
    # enfants inclus
    child_rows = EventChild.query.filter_by(event_id=ev.id, included=True).all()
    included_children = {r.child_id: r for r in child_rows}

    return render_template(
        "events/verify.html",
        ev=ev,
        parents=parents,
        included_children=included_children,
        actor=actor,
    )

# ---------------------------------------------------------------------
# API STATUS (admin + token)
# ---------------------------------------------------------------------
@events_bp.route("/api/<int:event_id>/status")
@login_required
def api_status_admin(event_id: int):
    ev = Event.query.get_or_404(event_id)
    return jsonify(_event_status_payload(ev))

@events_bp.route("/api/token/<token>/status")
def api_status_token(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    return jsonify(_event_status_payload(ev))

# ---------------------------------------------------------------------
# API VERIFY (secouristes)
# ---------------------------------------------------------------------
@events_bp.route("/api/<token>/verify", methods=["POST"])
def api_verify(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    state = bool(data.get("verified"))

    if not item_id:
        return jsonify({"error": "missing_item"}), 400

    # vérifier que l’item est inclus pour cet event
    ec = EventChild.query.filter_by(event_id=ev.id, child_id=item_id).first()
    if not ec or not ec.included:
        return jsonify({"error": "not_included"}), 400

    # identifier l’acteur via cookie “actor”
    actor = (request.cookies.get("actor") or "").strip()
    if not actor:
        return jsonify({"error": "auth"}), 401

    ec.verified = state
    ec.verified_by = actor if state else None
    ec.verified_at = datetime.utcnow() if state else None
    db.session.add(ec)
    db.session.add(EventLog(event_id=ev.id, actor=actor, action=f"verify:{item_id}:{state}"))

    # présence: ping le parent le plus proche
    parent_id = _closest_parent_id(item_id)
    if parent_id:
        _upsert_presence(ev.id, parent_id, actor)

    db.session.commit()
    return jsonify({"ok": True})

def _closest_parent_id(item_id: int):
    item = Item.query.get(item_id)
    if not item:
        return None
    if item.parent_id:
        return item.parent_id
    return None

def _upsert_presence(event_id: int, parent_id: int, actor: str):
    p = EventPresence.query.filter_by(event_id=event_id, parent_id=parent_id, actor=actor).first()
    if not p:
        p = EventPresence(event_id=event_id, parent_id=parent_id, actor=actor, last_seen=datetime.utcnow())
        db.session.add(p)
    else:
        p.last_seen = datetime.utcnow()
    return p

# ---------------------------------------------------------------------
# API LOAD (chef/admin)
# ---------------------------------------------------------------------
@events_bp.route("/api/<int:event_id>/load", methods=["POST"])
@login_required
def api_toggle_loaded(event_id: int):
    if not _is_admin_or_chef():
        abort(403)
    ev = Event.query.get_or_404(event_id)
    data = request.get_json(silent=True) or {}
    parent_id = data.get("item_id")
    state = bool(data.get("loaded"))

    if not parent_id:
        return jsonify({"error": "missing_parent"}), 400

    # sécurité: on vérifie que tous les enfants inclus sous ce parent sont verified=True
    # (si tu veux désactiver ce verrou, commente le bloc)
    all_ok = True
    for ec in EventChild.query.filter_by(event_id=ev.id, included=True).all():
        if _is_descendant_of(ec.child_id, parent_id):
            if not ec.verified:
                all_ok = False
                break
    if state and not all_ok:
        return jsonify({"error": "not_all_children_verified"}), 400

    row = EventLoad.query.filter_by(event_id=ev.id, parent_id=parent_id).first()
    if not row:
        row = EventLoad(event_id=ev.id, parent_id=parent_id, loaded=state)
        db.session.add(row)
    else:
        row.loaded = state

    db.session.add(EventLog(event_id=ev.id, actor=getattr(current_user, "username", "chef"), action=f"load:{parent_id}:{state}"))
    db.session.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------
# API PRESENCE (secouristes ping)
# ---------------------------------------------------------------------
@events_bp.route("/api/<token>/presence", methods=["POST"])
def api_presence(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    data = request.get_json(silent=True) or {}
    parent_id = data.get("parent_id")
    actor = (request.cookies.get("actor") or "").strip()
    if not actor or not parent_id:
        return jsonify({"error": "bad_request"}), 400
    _upsert_presence(ev.id, int(parent_id), actor)
    db.session.commit()
    return jsonify({"ok": True})
