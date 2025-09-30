# app/events/views.py
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Dict, List

from flask import Blueprint, request, jsonify, abort, current_app
from flask_login import login_required, current_user

from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    StockNode,
    NodeType,
    VerificationRecord,
    EventNodeStatus,
    event_stock,
    Role,
)
from ..tree_query import build_event_tree

# Optional: SocketIO (si présent dans le projet)
try:
    from .. import socketio  # type: ignore
except Exception:  # pragma: no cover
    socketio = None  # fallback

bp = Blueprint("events_api", __name__)

# -----------------------------
# Helpers
# -----------------------------
def _is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == Role.ADMIN

def _is_manager() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

def _event_or_404(event_id: int) -> Event:
    ev = db.session.get(Event, int(event_id))
    if not ev:
        abort(404, description="Événement introuvable.")
    return ev

def _event_from_token_or_404(token: str) -> Event:
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404, description="Lien public invalide.")
    return link.event

def _status_is_open(ev: Event) -> bool:
    status_raw = getattr(ev.status, "name", ev.status)
    return str(status_raw).upper() == "OPEN"

def _emit(channel: str, payload: dict) -> None:
    try:
        if socketio is not None:
            socketio.emit(channel, payload, room=f"event_{payload.get('event_id')}")
    except Exception:
        pass

def _all_items_ok(subtree: Dict[str, Any]) -> bool:
    ok = True
    has_item = False

    def rec(n: Dict[str, Any]):
        nonlocal ok, has_item
        ntype = (n.get("type") or "").upper()
        if ntype == "ITEM":
            has_item = True
            last_status = (n.get("last_status") or "").upper()
            ok = ok and (last_status == "OK")
        for c in n.get("children") or []:
            rec(c)

    rec(subtree)
    return has_item and ok

def _find_node(tree: List[Dict[str, Any]], node_id: int) -> Dict[str, Any] | None:
    for n in tree:
        if int(n.get("id")) == int(node_id):
            return n
        child = _find_node(n.get("children") or [], node_id)
        if child:
            return child
    return None


# -----------------------------------
# ÉVÉNEMENT (INTERNE — nécessite login)
# -----------------------------------

@bp.get("/events/<int:event_id>/tree")
@login_required
def event_tree(event_id: int):
    ev = _event_or_404(event_id)
    # Vérif droit lecture (ADMIN/CHEF/VIEWER)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)
    tree = build_event_tree(ev.id)
    return jsonify(tree)

@bp.post("/events/<int:event_id>/verify")
@login_required
def event_verify(event_id: int):
    ev = _event_or_404(event_id)
    if not _is_manager():
        abort(403)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    data = request.get_json(silent=True) or {}
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or current_user.username or "").strip()
    if not node_id or status not in ("OK", "NOT_OK"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Élément introuvable.")
    if node.type != NodeType.ITEM:
        abort(400, description="Seuls les items peuvent être vérifiés.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name
    )
    db.session.add(rec)
    db.session.commit()

    _emit(
        "event_update",
        {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
    )
    return jsonify({"ok": True, "record_id": rec.id})

@bp.post("/events/<int:event_id>/parent-status")
@login_required
def event_parent_status(event_id: int):
    ev = _event_or_404(event_id)
    if not _is_manager():
        abort(403)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — modification impossible."}), 403

    data = request.get_json(silent=True) or {}
    node_id = int(data.get("node_id") or 0)
    charged_vehicle = bool(data.get("charged_vehicle"))
    vehicle_name = (data.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")

    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(400, description="Seuls les parents (GROUP) sont concernés.")

    ens = (
        EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
        or EventNodeStatus(event_id=ev.id, node_id=node.id)
    )
    ens.charged_vehicle = charged_vehicle
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None

    db.session.add(ens)
    db.session.commit()

    payload = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
    }
    if hasattr(ens, "charged_vehicle_name"):
        payload["vehicle_name"] = ens.charged_vehicle_name
    _emit("event_update", payload)

    return jsonify({"ok": True})

@bp.patch("/events/<int:event_id>/status")
@login_required
def event_set_status(event_id: int):
    ev = _event_or_404(event_id)
    if not _is_manager():
        abort(403)

    data = request.get_json(silent=True) or {}
    status_raw = (data.get("status") or "").upper()
    if status_raw not in ("OPEN", "CLOSED"):
        abort(400, description="status invalide (OPEN|CLOSED).")

    ev.status = EventStatus.OPEN if status_raw == "OPEN" else EventStatus.CLOSED
    db.session.commit()
    return jsonify({"ok": True, "status": status_raw})

@bp.post("/events/<int:event_id>/share-link")
@login_required
def event_share_link(event_id: int):
    ev = _event_or_404(event_id)
    if not _is_manager():
        abort(403)

    # Réutiliser un lien actif si présent, sinon en créer un
    link = EventShareLink.query.filter_by(event_id=ev.id, active=True).first()
    if not link:
        token = secrets.token_urlsafe(16)
        link = EventShareLink(event_id=ev.id, token=token, active=True)
        db.session.add(link)
        db.session.commit()

    url = f"/public/event/{link.token}"
    return jsonify({"ok": True, "token": link.token, "url": url})


# -----------------------------------
# PUBLIC (Secouristes via lien partagé)
# -----------------------------------

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    ev = _event_from_token_or_404(token)
    tree = build_event_tree(ev.id)
    return jsonify(tree)

@bp.post("/public/event/<token>/verify")
def public_verify(token: str):
    ev = _event_from_token_or_404(token)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    data = request.get_json(silent=True) or {}
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name).")

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Élément introuvable.")
    if node.type != NodeType.ITEM:
        abort(400, description="Seuls les items peuvent être vérifiés.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name
    )
    db.session.add(rec)
    db.session.commit()

    _emit(
        "event_update",
        {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
    )
    return jsonify({"ok": True, "record_id": rec.id})

@bp.post("/public/event/<token>/charge")
def public_charge(token: str):
    ev = _event_from_token_or_404(token)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — chargement impossible."}), 403

    data = request.get_json(silent=True) or {}
    node_id = int(data.get("node_id") or 0)
    vehicle_name = (data.get("vehicle_name") or "").strip()
    operator_name = (data.get("operator_name") or "").strip()

    if not node_id or not vehicle_name:
        abort(400, description="Paramètres invalides (node_id, vehicle_name).")

    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(400, description="Le chargement est réservé aux parents (GROUP).")

    # Vérifier que le node est bien une racine de l'événement
    present = db.session.execute(
        event_stock.select().where(
            event_stock.c.event_id == ev.id,
            event_stock.c.node_id == node.id,
        )
    ).first()
    if not present:
        abort(400, description="Seules les racines de l’événement peuvent être chargées.")

    # Vérifier que tous les items descendants sont OK
    try:
        tree = build_event_tree(ev.id)
        sub = _find_node(tree, node.id)
        if sub is not None and not _all_items_ok(sub):
            abort(400, description="Impossible de charger : tous les sous-éléments doivent être OK.")
    except Exception:
        # Si on ne peut pas vérifier, on laisse l’UI protéger (fail-soft)
        pass

    ens = (
        EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
        or EventNodeStatus(event_id=ev.id, node_id=node.id)
    )
    ens.charged_vehicle = True
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name
    db.session.add(ens)
    db.session.commit()

    payload = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": True,
    }
    if hasattr(ens, "charged_vehicle_name"):
        payload["vehicle_name"] = ens.charged_vehicle_name
    _emit("event_update", payload)

    return jsonify({"ok": True, "node_id": node.id, "vehicle": vehicle_name, "by": operator_name})
