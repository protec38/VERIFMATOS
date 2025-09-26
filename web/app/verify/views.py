# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict
from flask import Blueprint, render_template, request, jsonify, abort
from sqlalchemy import select, exists
from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    StockNode,
    NodeType,
    event_stock,
    VerificationRecord,
)
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

# --- Page publique (affichage + état initial persistant) ---
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    # arbre avec états (last_status, last_by, complete, etc.)
    tree = build_event_tree(ev.id)
    return render_template("public_event.html", token=token, event=ev, tree=tree)

# --- Vérification publique d’un item (OK / NOT_OK) ---
@bp.post("/public/event/<token>/verify")
def public_verify(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev: Event = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé")

    data = _json()
    try:
        node_id = int(data.get("node_id") or 0)
    except Exception:
        node_id = 0
    status = (data.get("status") or "").upper()  # "OK" | "NOT_OK"
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides")

    # Optionnel: vérifier que node_id est bien un ITEM rattaché à l'événement
    is_item = db.session.get(StockNode, node_id)
    if not is_item or is_item.type != NodeType.ITEM:
        abort(400, description="node_id doit être un ITEM")

    # Vérifie que ce node est dans un sous-arbre rattaché à cet événement (coût raisonnable)
    # -> on vérifie que au moins un root associé est ancêtre de node_id
    root_ids = [r.id for r in db.session.scalars(
        select(StockNode).join(event_stock, event_stock.c.node_id == StockNode.id).where(
            event_stock.c.event_id == ev.id, StockNode.level == 0, StockNode.type == NodeType.GROUP
        )
    ).all()]

    if not root_ids:
        abort(400, description="Aucun stock parent associé à l'événement")

    # Remonte la chaîne parentale pour trouver un root
    cur = is_item
    ok_root = False
    while cur is not None:
        if cur.id in root_ids:
            ok_root = True
            break
        cur = db.session.get(StockNode, cur.parent_id) if cur.parent_id else None
    if not ok_root:
        abort(400, description="Item hors périmètre de l'événement")

    # Enregistre
    rec = VerificationRecord(event_id=ev.id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()

    # Diffuse aux clients du même event (temps réel)
    try:
        socketio.emit("event_update",
                      {"type": "item_verified", "event_id": ev.id, "node_id": node_id,
                       "status": status, "by": verifier_name},
                      room=f"event_{ev.id}")
    except Exception:
        pass

    return jsonify({"ok": True, "record_id": rec.id})
