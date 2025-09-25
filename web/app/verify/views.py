# app/verify/views.py — Vérification items + statut parent (REST) + diffusion temps réel
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from .. import db, socketio
from ..models import (
    Event, EventStatus, VerificationRecord, ItemStatus,
    EventNodeStatus, StockNode, NodeType, EventShareLink, Role
)

bp = Blueprint("verify", __name__)

def room_for_event(event_id: int) -> str:
    return f"event-{event_id}"

def can_manage_event():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

# ---- Authenticated endpoints (chefs/admin/viewer lecture seule) ----

@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    # VIEWER ne doit pas modifier
    if current_user.role == Role.VIEWER:
        return jsonify(error="Forbidden"), 403

    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Event not found"), 404
    if ev.status != EventStatus.OPEN:
        return jsonify(error="Event is CLOSED"), 403

    data = request.get_json() or {}
    node_id = data.get("node_id")
    status_str = (data.get("status") or "OK").upper()
    verifier_name = data.get("verifier_name")
    comment = data.get("comment")

    if not node_id or not verifier_name:
        return jsonify(error="node_id and verifier_name required"), 400
    node = db.session.get(StockNode, int(node_id))
    if not node or node.type != NodeType.ITEM:
        return jsonify(error="Invalid node (must be ITEM)"), 400

    try:
        status = ItemStatus[status_str]
    except KeyError:
        return jsonify(error="Invalid status"), 400

    rec = VerificationRecord(
        event_id=event_id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name.strip()[:120],
        comment=comment[:1000] if comment else None,
    )
    db.session.add(rec)
    db.session.commit()

    payload = {
        "type": "item_verified",
        "event_id": event_id,
        "node_id": node.id,
        "status": status.name,
        "verifier_name": rec.verifier_name,
        "comment": rec.comment,
        "created_at": rec.created_at.isoformat()
    }
    socketio.emit("event_update", payload, to=room_for_event(event_id))
    return jsonify(ok=True, **payload)

@bp.post("/events/<int:event_id>/parent-status")
@login_required
def parent_status(event_id: int):
    # VIEWER ne doit pas modifier
    if current_user.role == Role.VIEWER:
        return jsonify(error="Forbidden"), 403

    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Event not found"), 404
    if ev.status != EventStatus.OPEN:
        return jsonify(error="Event is CLOSED"), 403

    data = request.get_json() or {}
    node_id = data.get("node_id")
    charged = bool(data.get("charged_vehicle", False))
    comment = data.get("comment")

    if not node_id:
        return jsonify(error="node_id required"), 400
    node = db.session.get(StockNode, int(node_id))
    if not node or node.type != NodeType.GROUP:
        return jsonify(error="Invalid node (must be GROUP)"), 400

    # upsert
    ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=event_id, node_id=node.id, charged_vehicle=charged, comment=comment)
        db.session.add(ens)
    else:
        ens.charged_vehicle = charged
        ens.comment = comment
    db.session.commit()

    payload = {
        "type": "parent_status",
        "event_id": event_id,
        "node_id": node.id,
        "charged_vehicle": ens.charged_vehicle,
        "comment": ens.comment
    }
    socketio.emit("event_update", payload, to=room_for_event(event_id))
    return jsonify(ok=True, **payload)

# ---- Public endpoints via token (secouristes) ----

@bp.post("/public/<token>/verify")
def public_verify(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        return jsonify(error="Invalid link"), 404
    ev = link.event
    if ev.status != EventStatus.OPEN:
        return jsonify(error="Event is CLOSED"), 403

    data = request.get_json() or {}
    node_id = data.get("node_id")
    status_str = (data.get("status") or "OK").upper()
    verifier_name = data.get("verifier_name")
    comment = data.get("comment")

    if not node_id or not verifier_name:
        return jsonify(error="node_id and verifier_name required"), 400
    node = db.session.get(StockNode, int(node_id))
    if not node or node.type != NodeType.ITEM:
        return jsonify(error="Invalid node (must be ITEM)"), 400

    try:
        status = ItemStatus[status_str]
    except KeyError:
        return jsonify(error="Invalid status"), 400

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name.strip()[:120],
        comment=comment[:1000] if comment else None,
    )
    db.session.add(rec)
    db.session.commit()

    payload = {
        "type": "item_verified",
        "event_id": ev.id,
        "node_id": node.id,
        "status": status.name,
        "verifier_name": rec.verifier_name,
        "comment": rec.comment,
        "created_at": rec.created_at.isoformat()
    }
    socketio.emit("event_update", payload, to=room_for_event(ev.id))
    return jsonify(ok=True, **payload)
