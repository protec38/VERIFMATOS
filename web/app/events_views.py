# app/events_views.py — Blueprint Events (CRUD événements, partage, attacher stock)
import secrets
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from . import db
from .models import Event, EventStatus, EventShareLink, StockNode, NodeType, event_stock

bp = Blueprint("events", __name__)

def require_manager():
    return current_user.is_authenticated and current_user.can_manage_events

@bp.post("/events")
@login_required
def create_event():
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    name = data.get("name")
    date_str = data.get("date")
    try:
        date = datetime.fromisoformat(date_str).date() if date_str else None
    except Exception:
        return jsonify(error="Invalid date"), 400
    ev = Event(name=name, date=date, status=EventStatus.OPEN, created_by_id=current_user.id)
    db.session.add(ev)
    db.session.commit()
    return jsonify(id=ev.id, name=ev.name, status=ev.status.name)

@bp.get("/events")
@login_required
def list_events():
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    events = Event.query.order_by(Event.date.desc()).all()
    return jsonify([{"id": e.id, "name": e.name, "date": e.date.isoformat() if e.date else None, "status": e.status.name} for e in events])

@bp.patch("/events/<int:event_id>/status")
@login_required
def set_status(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    data = request.get_json() or {}
    status = data.get("status", "").upper()
    try:
        ev.status = EventStatus[status]
    except KeyError:
        return jsonify(error="Invalid status"), 400
    db.session.commit()
    return jsonify(id=ev.id, status=ev.status.name)

@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    token = secrets.token_urlsafe(24)
    link = EventShareLink(token=token, event_id=event_id, active=True)
    db.session.add(link)
    db.session.commit()
    return jsonify(token=token, url=f"/public/{token}")

@bp.get("/public/<token>")
def public_event_meta(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        return jsonify(error="Invalid link"), 404
    ev = link.event
    return jsonify(event_id=ev.id, name=ev.name, date=ev.date.isoformat() if ev.date else None,
                   status=ev.status.name, can_edit=(ev.status == EventStatus.OPEN))

@bp.post("/events/<int:event_id>/attach-roots")
@login_required
def attach_roots(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    data = request.get_json() or {}
    ids = data.get("node_ids", [])
    if not isinstance(ids, list) or not ids:
        return jsonify(error="node_ids list required"), 400
    added = []
    for nid in ids:
        node = db.session.get(StockNode, int(nid))
        if not node:
            return jsonify(error=f"node {nid} not found"), 404
        if node.parent_id is not None:
            return jsonify(error=f"node {nid} is not a root (parent_id must be null)"), 400
        if node.type != NodeType.GROUP:
            return jsonify(error=f"node {nid} must be GROUP"), 400
        ins = db.session.execute(event_stock.select().where(
            (event_stock.c.event_id == event_id) & (event_stock.c.node_id == node.id)
        )).first()
        if not ins:
            db.session.execute(event_stock.insert().values(event_id=event_id, node_id=node.id))
            added.append(node.id)
    db.session.commit()
    return jsonify(added=added)

@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def list_roots(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    rows = db.session.execute(
        event_stock.select().where(event_stock.c.event_id == event_id)
    ).fetchall()
    node_ids = [r.node_id for r in rows]
    nodes = StockNode.query.filter(StockNode.id.in_(node_ids)).all() if node_ids else []
    return jsonify([{"id": n.id, "name": n.name, "level": n.level, "type": n.type.name} for n in nodes])
