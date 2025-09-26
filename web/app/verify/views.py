# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict
from flask import Blueprint, jsonify, request, abort, render_template
from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    VerificationRecord,
    StockNode,
    NodeType,
    event_stock,
)
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

# --- Page publique (affiche l’arbre) ---
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    # Construit l’arbre avec last_status/last_by
    tree = build_event_tree(ev.id)
    return render_template("public_event.html", token=token, event=ev, tree=tree)

# --- Vérification publique d’un item ---
@bp.post("/public/event/<token>/verify")
def public_verify_item(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé")

    data = _json()
    try:
        node_id = int(data.get("node_id") or 0)
    except Exception:
        node_id = 0
    status = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides")

    # (optionnel) Sécurité : vérifier que node_id appartient bien aux racines associées à l'événement
    # Vérification rapide : le node doit exister
    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Item introuvable")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name,
    )
    db.session.add(rec)
    db.session.commit()

    # Temps réel : on notifie la room de l’événement
    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass

    return jsonify({"ok": True, "record_id": rec.id})
