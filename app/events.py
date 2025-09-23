from __future__ import annotations
from datetime import datetime
import uuid

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    jsonify, session, abort
)
from flask_login import login_required, current_user

from . import db
from .models import (
    User, Item, Event, EventParent, EventChild, EventLoad,
    EventPresence, EventLog
)

events_bp = Blueprint("events", __name__)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _now():
    return datetime.utcnow()

def _ensure_token(ev: Event) -> None:
    if not ev.token:
        ev.token = str(uuid.uuid4())
        db.session.add(ev)
        db.session.commit()

def _descendant_leaves(item: Item) -> list[Item]:
    """Return all leaf items under item (including nested sub-parents)."""
    leaves = []
    stack = [item]
    while stack:
        it = stack.pop()
        # children is a query (lazy='dynamic')
        kids = list(it.children.order_by(Item.id.asc()).all())
        if not kids:
            # treat as leaf if no children OR kind == 'leaf'
            if it.kind == "leaf" or not it.children.count():
                leaves.append(it)
        else:
            any_child = True
            # if any children exist, push them;
            # but if item.kind == leaf and has children (inconsistent), still dive.
            stack.extend(kids)
            # If this is a 'leaf' with kids, we don't add self.
    return [x for x in leaves if x.kind == "leaf"]

def _included_children_for_event(ev: Event, parent: Item) -> list[EventChild]:
    """Return EventChild rows for the leaf descendants of parent, creating missing rows as included=True."""
    leaves = _descendant_leaves(parent)
    existing = { (ec.child_id): ec for ec in EventChild.query.filter_by(event_id=ev.id).filter(EventChild.child_id.in_([l.id for l in leaves])).all() }
    created = []
    for leaf in leaves:
        if leaf.id not in existing:
            ec = EventChild(
                event_id=ev.id,
                child_id=leaf.id,
                included=True,
                verified=False
            )
            db.session.add(ec)
            created.append(ec)
    if created:
        db.session.commit()
        existing.update({ec.child_id: ec for ec in created})
    # return in item order
    return [existing[l.id] for l in leaves]

def _parent_block(ev: Event, parent: Item) -> dict:
    """Build the structure used by templates for one parent block."""
    ecs = _included_children_for_event(ev, parent)
    # loaded state row (create if missing)
    load = EventLoad.query.filter_by(event_id=ev.id, parent_id=parent.id).first()
    if not load:
        load = EventLoad(event_id=ev.id, parent_id=parent.id, loaded=False)
        db.session.add(load)
        db.session.commit()

    # Compute completion
    included_ecs = [ec for ec in ecs if ec.included]
    complete = all(ec.verified for ec in included_ecs) if included_ecs else False

    # Busy list (presence)
    pres = EventPresence.query.filter_by(event_id=ev.id, parent_id=parent.id).all()
    busy = sorted({p.actor for p in pres})

    return {
        "parent": parent,
        "load": load,
        "children": ecs,
        "complete": complete,
        "busy": busy,
    }

def _parents_context(ev: Event) -> list[dict]:
    parents = Item.query.filter_by(kind="parent").order_by(Item.id.asc()).all()
    # keep only those associated to event via EventParent
    parent_ids = [ep.parent_id for ep in EventParent.query.filter_by(event_id=ev.id).all()]
    parents = [p for p in parents if p.id in parent_ids]
    return [_parent_block(ev, p) for p in parents]

def _compute_status_payload(ev: Event) -> dict:
    # verifications
    verifs = {}
    ecs = EventChild.query.filter_by(event_id=ev.id).all()
    for ec in ecs:
        verifs[str(ec.child_id)] = {
            "verified": bool(ec.verified),
            "by": ec.verified_by or None,
            "at": ec.verified_at.isoformat() if ec.verified_at else None,
        }
    # parents_complete and loaded and busy
    parents_complete = {}
    loaded = {}
    busy = {}
    epars = EventParent.query.filter_by(event_id=ev.id).all()
    for ep in epars:
        block = _parent_block(ev, ep.parent)
        parents_complete[str(ep.parent_id)] = bool(block["complete"])
        loaded[str(ep.parent_id)] = bool(block["load"].loaded)
        busy[str(ep.parent_id)] = block["busy"]
    return {
        "verifications": verifs,
        "parents_complete": parents_complete,
        "loaded": loaded,
        "busy": busy,
    }

# ------------------------------------------------------------
# Views
# ------------------------------------------------------------

@events_bp.route("/")
@login_required
def list_events():
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template("events/list.html", events=events)

@events_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_event():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("date", "").strip()
        location = request.form.get("location", "").strip()
        sel_parents = request.form.getlist("parents")

        if not title:
            flash("Titre requis", "danger")
            return redirect(url_for("events.new_event"))

        try:
            date = datetime.fromisoformat(date_str) if date_str else _now()
        except Exception:
            date = _now()

        ev = Event(title=title, date=date, location=location, state="draft")
        db.session.add(ev)
        db.session.commit()

        # attach selected parents
        parent_ids = [int(pid) for pid in sel_parents if pid.isdigit()]
        for pid in parent_ids:
            p = Item.query.get(pid)
            if p and p.kind == "parent":
                db.session.add(EventParent(event_id=ev.id, parent_id=p.id))
        db.session.commit()

        # Pre-create EventChild for leaves under selected parents
        epars = EventParent.query.filter_by(event_id=ev.id).all()
        for ep in epars:
            _included_children_for_event(ev, ep.parent)

        # Generate token immediately for sharing
        _ensure_token(ev)

        flash("Événement créé.", "success")
        return redirect(url_for("events.view_event", event_id=ev.id))

    # GET
    parents = Item.query.filter_by(kind="parent").order_by(Item.name.asc()).all()
    return render_template("events/new.html", parents=parents)

@events_bp.route("/<int:event_id>")
@login_required
def view_event(event_id: int):
    ev = Event.query.get_or_404(event_id)
    _ensure_token(ev)
    parents = _parents_context(ev)
    # Share link shown in template using ev.token
    return render_template("events/detail.html", ev=ev, parents=parents)

# ------------------------------------------------------------
# VERIFY (Secouristes)
# ------------------------------------------------------------

@events_bp.route("/verify/<token>/access", methods=["GET", "POST"])
def verify_access(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    if request.method == "POST":
        first = request.form.get("first_name", "").strip()
        last = request.form.get("last_name", "").strip()
        if not first or not last:
            flash("Nom et prénom requis.", "danger")
            return redirect(url_for("events.verify_access", token=token))
        actor = f"{first} {last}"
        session[f"rescuer:{token}"] = actor
        # Optional: allow choosing a parent to start; here we just go to page
        return redirect(url_for("events.verify", token=token))
    return render_template("events/verify_access.html", ev=ev)

@events_bp.route("/verify/<token>")
def verify(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    actor = session.get(f"rescuer:{token}")
    # Build parents blocks
    parents = _parents_context(ev)
    return render_template("events/verify.html", ev=ev, parents=parents, actor=actor)

# ------------------------------------------------------------
# API status (polling)
# ------------------------------------------------------------

@events_bp.route("/api/<int:event_id>/status")
@login_required
def api_status_admin(event_id: int):
    ev = Event.query.get_or_404(event_id)
    return jsonify(_compute_status_payload(ev))

@events_bp.route("/api/token/<token>/status")
def api_status_token(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    return jsonify(_compute_status_payload(ev))

# ------------------------------------------------------------
# API verify (toggle by rescuer)
# ------------------------------------------------------------

@events_bp.route("/api/<token>/verify", methods=["POST"])
def api_verify(token: str):
    ev = Event.query.filter_by(token=token).first_or_404()
    actor = session.get(f"rescuer:{token}")
    if not actor:
        return jsonify({"error": "auth"}), 401

    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    state = bool(data.get("verified"))
    if not isinstance(item_id, int):
        try:
            item_id = int(item_id)
        except Exception:
            return jsonify({"error": "bad_request"}), 400

    # The item must be included leaf for this event
    ec = EventChild.query.filter_by(event_id=ev.id, child_id=item_id).first()
    if not ec or not ec.included:
        return jsonify({"error": "not_included"}), 400

    ec.verified = state
    ec.verified_by = actor if state else None
    ec.verified_at = _now() if state else None
    db.session.add(ec)

    # presence (mark rescuer busy on the parent of that leaf)
    # find parent via EventParent mapping: we need the top-most selected parent that is ancestor of this leaf
    # compute by scanning all event parents and checking ancestry
    parent_id = None
    epars = EventParent.query.filter_by(event_id=ev.id).all()
    leaf = Item.query.get(item_id)
    if leaf:
        for ep in epars:
            # is ep.parent ancestor of leaf?
            cur = leaf
            found = False
            while cur and cur.parent_id is not None:
                if cur.parent_id == ep.parent_id:
                    found = True
                    break
                cur = Item.query.get(cur.parent_id)
            if found or (leaf.parent_id == ep.parent_id):
                parent_id = ep.parent_id
                break

    if parent_id:
        pres = EventPresence.query.filter_by(event_id=ev.id, parent_id=parent_id, actor=actor).first()
        if not pres:
            pres = EventPresence(event_id=ev.id, parent_id=parent_id, actor=actor, last_seen=_now())
        else:
            pres.last_seen = _now()
        db.session.add(pres)

    # log
    db.session.add(EventLog(event_id=ev.id, actor=actor, action=f"{'Vérifié' if state else 'Décoché'} leaf#{item_id}", at=_now()))

    db.session.commit()
    return jsonify({"ok": True})

# ------------------------------------------------------------
# API load (toggle loaded by chef/admin)
# ------------------------------------------------------------

@events_bp.route("/api/<int:event_id>/load", methods=["POST"])
@login_required
def api_load(event_id: int):
    ev = Event.query.get_or_404(event_id)
    data = request.get_json(silent=True) or {}
    parent_id = data.get("item_id")
    state = bool(data.get("loaded"))
    try:
        parent_id = int(parent_id)
    except Exception:
        return jsonify({"error": "bad_request"}), 400

    ep = EventParent.query.filter_by(event_id=ev.id, parent_id=parent_id).first()
    if not ep:
        return jsonify({"error": "unknown_parent"}), 404

    # must be complete before loading true
    block = _parent_block(ev, ep.parent)
    if state and not block["complete"]:
        return jsonify({"error": "not_all_children_verified"}), 400

    load = EventLoad.query.filter_by(event_id=ev.id, parent_id=parent_id).first()
    if not load:
        load = EventLoad(event_id=ev.id, parent_id=parent_id, loaded=False)
    load.loaded = state
    db.session.add(load)

    db.session.add(EventLog(event_id=ev.id, actor=(current_user.username if current_user.is_authenticated else "chef"), action=f"{'Chargé' if state else 'Déchargé'} parent#{parent_id}", at=_now()))
    db.session.commit()
    return jsonify({"ok": True})

# ------------------------------------------------------------
# Export (CSV des logs)
# ------------------------------------------------------------

@events_bp.route("/<int:event_id>/logs.csv")
@login_required
def logs_csv(event_id: int):
    ev = Event.query.get_or_404(event_id)
    import csv
    from io import StringIO
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["at", "actor", "action"])
    for a in EventLog.query.filter_by(event_id=ev.id).order_by(EventLog.at.asc()).all():
        cw.writerow([a.at.isoformat() if a.at else "", a.actor or "", a.action or ""])
    from flask import Response
    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=event_{ev.id}_logs.csv"},
    )
