# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict
from flask import Blueprint, render_template, jsonify, request, abort
from .. import db, socketio
from ..models import EventShareLink, EventStatus, VerificationRecord
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

def _get_json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict(flat=True) if request.form else {}
    return data

@bp.get("/public/event/<token>")
def public_event_page(token: str):
    """Page publique (secouristes) — avec arbre injecté pour éviter les fetch inutiles."""
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id)  # << IMPORTANT
    return render_template("public_event.html", token=token, event=ev, tree=tree)

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    """JSON de secours si on veut recharger l’arbre côté client."""
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    return jsonify(build_event_tree(link.event_id))

@bp.post("/public/event/<token>/verify")
def public_verify_item(token: str):
    """Enregistre une vérification (OK/NOT_OK) sans compte, via le lien partagé."""
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement clôturé")

    data = _get_json()
    try:
        node_id = int(data.get("node_id") or 0)
    except Exception:
        node_id = 0
    status = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name)")

    rec = VerificationRecord(event_id=ev.id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()

    # notif socket (best effort)
    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass

    return jsonify({"ok": True, "record_id": rec.id})
