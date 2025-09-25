# app/events/views.py — Événements, statut, partage public, rattachement stocks
import secrets
from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from .. import db
from ..models import Event, EventStatus, Role, StockNode, NodeType, event_stock, EventShareLink

bp = Blueprint("events", __name__)

def require_manager():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

# Créer un événement
@bp.post("/events")
@login_required
def create_event():
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    name = data.get("name")
    date_str = data.get("date")
    if not name:
        return jsonify(error="name required"), 400
    date = None
    if date_str:
        try:
            date = datetime.fromisoformat(date_str).date()
        except Exception:
            return jsonify(error="invalid date"), 400
    ev = Event(name=name, date=date, status=EventStatus.OPEN, created_by_id=current_user.id)
    db.session.add(ev)
    db.session.commit()
    return jsonify(id=ev.id, name=ev.name, date=ev.date.isoformat() if ev.date else None, status=ev.status.name)

# Changer le statut (OPEN/CLOSED)
@bp.patch("/events/<int:event_id>/status")
@login_required
def set_status(event_id:int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    data = request.get_json() or {}
    status_str = (data.get("status") or "").upper()
    try:
        ev.status = EventStatus[status_str]
    except KeyError:
        return jsonify(error="Invalid status"), 400
    db.session.commit()
    return jsonify(id=ev.id, status=ev.status.name)

# Générer un lien de partage public
@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id:int):
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

# Métadonnées publiques de l'événement (pour la page secouristes)
@bp.get("/public/<token>")
def public_meta(token:str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        return jsonify(error="Invalid link"), 404
    ev = link.event
    return jsonify(event_id=ev.id, name=ev.name, date=ev.date.isoformat() if ev.date else None,
                   status=ev.status.name, can_edit=(ev.status == EventStatus.OPEN))

# Attacher des racines de stock à un événement
@bp.post("/events/<int:event_id>/attach-roots")
@login_required
def attach_roots(event_id:int):
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
            return jsonify(error=f"node {nid} is not a root"), 400
        if node.type != NodeType.GROUP:
            return jsonify(error=f"node {nid} must be GROUP"), 400
        # check existing
        exists = db.session.execute(event_stock.select().where(
            (event_stock.c.event_id == event_id) & (event_stock.c.node_id == node.id)
        )).first()
        if not exists:
            db.session.execute(event_stock.insert().values(event_id=event_id, node_id=node.id))
            added.append(node.id)
    db.session.commit()
    return jsonify(added=added)

# Lister les racines attachées
@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def list_roots(event_id:int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    rows = db.session.execute(event_stock.select().where(event_stock.c.event_id == event_id)).fetchall()
    node_ids = [r.node_id for r in rows]
    nodes = StockNode.query.filter(StockNode.id.in_(node_ids)).all() if node_ids else []
    return jsonify([{"id":n.id,"name":n.name,"level":n.level,"type":n.type.name} for n in nodes])
