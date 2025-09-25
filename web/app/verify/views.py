# app/verify/views.py — Lien public pour les secouristes
from __future__ import annotations
from typing import Any, Dict
from flask import Blueprint, jsonify, request, abort, render_template
from .. import db, socketio
from ..tree_query import build_event_tree
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    VerificationRecord,
    ItemStatus,
)

bp = Blueprint("verify_public", __name__)

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

def _event_from_token(token: str) -> Event:
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link:
        abort(404)
    ev = db.session.get(Event, link.event_id)
    if not ev:
        abort(404)
    return ev

# --- Page publique ---
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    ev = _event_from_token(token)
    return render_template("public_event.html", token=token, event=ev)

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    ev = _event_from_token(token)
    return jsonify(build_event_tree(ev.id))

@bp.post("/public/event/<token>/verify")
def public_verify(token: str):
    ev = _event_from_token(token)
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement clôturé.")
    data = _json()
    node_id = int(data.get("node_id") or 0)
    status_raw = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or "").strip()
    if not node_id or status_raw not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides.")
    status = ItemStatus.OK if status_raw == "OK" else ItemStatus.NOT_OK
    rec = VerificationRecord(event_id=ev.id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()
    try:
        socketio.emit("event_update", {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status_raw, "by": verifier_name}, room=f"event_{ev.id}")
    except Exception:
        pass
    return jsonify({"ok": True, "record_id": rec.id})
