# app/events/views.py — API JSON pour les événements (corrigé)
from __future__ import annotations
import uuid
from datetime import date
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from .. import db, socketio
from ..tree_query import build_event_tree
from ..models import (
    Event,
    EventStatus,
    Role,
    StockNode,
    event_stock,
    EventShareLink,
    EventNodeStatus,
    VerificationRecord,
    ItemStatus,
)

bp = Blueprint("events", __name__)

# ---------- helpers ----------
def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

def _require_admin():
    if not current_user.is_authenticated or current_user.role != Role.ADMIN:
        abort(403)

def _require_manage(ev: Event):
    if not current_user.is_authenticated or current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)
    if ev.status != EventStatus.OPEN:
        abort(403)

def _require_view(ev: Event):
    if not current_user.is_authenticated or current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)

# ---------- création / attache ----------
@bp.post("/events")
@login_required
def create_event():
    """Crée un événement + attache directement les parents sélectionnés."""
    if current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)
    data = _json()
    name = (data.get("name") or "").strip()
    date_str = (data.get("date") or "").strip()
    parent_ids: List[int] = data.get("parent_ids") or []
    if not name:
        abort(400, description="name requis")

    d = None
    if date_str:
        try:
            d = date.fromisoformat(date_str)
        except Exception:
            d = None

    # >>> CORRECTION ICI: on renseigne created_by_id <<<
    ev = Event(name=name, date=d, status=EventStatus.OPEN, created_by_id=current_user.id)
    db.session.add(ev)
    db.session.flush()  # pour ev.id

    # Attacher les parents si fournis
    if parent_ids:
        rows = (
            db.session.query(StockNode.id)
            .filter(StockNode.id.in_(parent_ids))
            .all()
        )
        for (nid,) in rows:
            db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=nid))

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id})

@bp.post("/events/<int:event_id>/attach-parents")
@login_required
def attach_parents(event_id: int):
    """Attache une liste de parents racine à l'événement (idempotent)."""
    ev = db.session.get(Event, event_id) or abort(404)
    _require_manage(ev)
    data = _json()
    parent_ids: List[int] = data.get("parent_ids") or []
    if not parent_ids:
        return jsonify({"ok": True, "attached": 0})

    existing = {
        row[0]
        for row in db.session.execute(
            db.select(event_stock.c.node_id).where(event_stock.c.event_id == event_id)
        ).all()
    }
    add_ids = [pid for pid in parent_ids if pid not in existing]
    for pid in add_ids:
        db.session.execute(event_stock.insert().values(event_id=event_id, node_id=pid))
    db.session.commit()
    return jsonify({"ok": True, "attached": len(add_ids)})

# ---------- lecture arbre / racines ----------
@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_view(ev)
    return jsonify(build_event_tree(event_id))

@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def get_event_roots(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_view(ev)
    roots = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
        .all()
    )
    return jsonify([{"id": r.id, "name": r.name} for r in roots])

# ---------- partage / statut ----------
@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_manage(ev)
    link = EventShareLink.query.filter_by(event_id=event_id, active=True).first()
    if not link:
        token = uuid.uuid4().hex
        link = EventShareLink(event_id=event_id, token=token, active=True)
        db.session.add(link)
        db.session.commit()
    return jsonify({"ok": True, "token": link.token, "url": f"/public/event/{link.token}"}), 201

@bp.get("/events/<int:event_id>/share-link")
@login_required
def get_share_link(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_view(ev)
    link = EventShareLink.query.filter_by(event_id=event_id, active=True).first()
    if not link:
        return jsonify({"ok": False, "error": "no_active_link"}), 404
    return jsonify({"ok": True, "token": link.token, "url": f"/public/event/{link.token}"})

@bp.route("/events/<int:event_id>/status", methods=["PATCH", "POST"])
@login_required
def update_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    data = _json()
    status = (data.get("status") or "").upper()
    if status == "CLOSED":
        _require_manage(ev)
        ev.status = EventStatus.CLOSED
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_closed", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "CLOSED"})
    elif status == "OPEN":
        _require_admin()
        ev.status = EventStatus.OPEN
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_opened", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "OPEN"})
    abort(400, description="Statut invalide.")

# ---------- vérification (interne) ----------
@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_manage(ev)
    data = _json()
    node_id = int(data.get("node_id") or 0)
    charged = bool(data.get("charged_vehicle"))
    if not node_id:
        abort(400, description="node_id manquant")
    ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=node_id).first()
    if not ens:
        ens = EventNodeStatus(event_id=event_id, node_id=node_id, charged_vehicle=charged)
    else:
        ens.charged_vehicle = charged
    db.session.add(ens)
    db.session.commit()
    try:
        socketio.emit("event_update", {"type": "parent_charged", "event_id": ev.id, "node_id": node_id, "charged": charged}, room=f"event_{ev.id}")
    except Exception:
        pass
    return jsonify({"ok": True, "node_id": node_id, "charged_vehicle": charged})

@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_manage(ev)
    data = _json()
    node_id = int(data.get("node_id") or 0)
    status_raw = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or "").strip()
    if not node_id or status_raw not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name).")
    status = ItemStatus.OK if status_raw == "OK" else ItemStatus.NOT_OK
    rec = VerificationRecord(event_id=event_id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()
    try:
        socketio.emit("event_update", {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status_raw, "by": verifier_name}, room=f"event_{ev.id}")
    except Exception:
        pass
    return jsonify({"ok": True, "record_id": rec.id})

@bp.get("/events/<int:event_id>/stats")
@login_required
def stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_view(ev)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status=ItemStatus.OK).count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})

@bp.delete("/events/<int:event_id>")
@login_required
def delete_event(event_id: int):
    _require_admin()
    ev = db.session.get(Event, event_id) or abort(404)
    VerificationRecord.query.filter_by(event_id=event_id).delete(synchronize_session=False)
    EventNodeStatus.query.filter_by(event_id=event_id).delete(synchronize_session=False)
    EventShareLink.query.filter_by(event_id=event_id).delete(synchronize_session=False)
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == event_id))
    db.session.delete(ev)
    db.session.commit()
    return jsonify({"ok": True, "deleted": event_id})
