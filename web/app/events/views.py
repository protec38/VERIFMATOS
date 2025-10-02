# app/events/views.py
from __future__ import annotations

import secrets
import json
from typing import Any, Dict, List
from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import select

from .. import db, socketio
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

bp_events = Blueprint("events_api", __name__, url_prefix="/events")
bp_public = Blueprint("public_api", __name__, url_prefix="/public")

# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _is_manager() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

def _can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

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

def _emit(event_name: str, payload: Dict[str, Any]):
    # S'il y a SocketIO, on émet localement (pas de Redis si non configuré)
    try:
        if socketio:
            socketio.emit(event_name, payload, namespace="/events")
    except Exception:
        # Ne jamais faire planter l'API pour un emit
        pass

# -------------------------------------------------
# Routes internes
# -------------------------------------------------
@bp_events.post("/")
@bp_events.post("")  # accepte /events ET /events/
@login_required
def create_event():
    if not _is_manager():
        abort(403)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    date_raw = (data.get("date") or "").strip() or None
    raw_roots = data.get("roots")
    root_specs: List[Dict[str, Any]] = []
    if isinstance(raw_roots, list) and raw_roots:
        for entry in raw_roots:
            if isinstance(entry, dict):
                root_specs.append({
                    "id": entry.get("id"),
                    "quantity": entry.get("quantity"),
                })
            else:
                root_specs.append({"id": entry, "quantity": None})
    else:
        root_ids = data.get("root_ids") or data.get("root_node_ids") or []
        if isinstance(root_ids, list):
            for rid in root_ids:
                root_specs.append({"id": rid, "quantity": None})

    if not name or not root_specs:
        abort(400, description="name et roots requis.")

    # date optionnelle
    dt = None
    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw).date()
        except Exception:
            abort(400, description="date invalide (YYYY-MM-DD).")

    ev = Event(
        name=name,
        date=dt,
        status=EventStatus.OPEN,
        created_by_id=current_user.id
    )
    db.session.add(ev)
    db.session.flush()

    seen = set()
    for spec in root_specs:
        nid = spec.get("id")
        try:
            nid_i = int(nid)
        except Exception:
            abort(400, description=f"root_id invalide: {nid}")
        if nid_i in seen:
            continue
        seen.add(nid_i)
        node = db.session.get(StockNode, nid_i)
        if not node:
            abort(400, description=f"StockNode {nid_i} introuvable.")
        if node.type != NodeType.GROUP:
            abort(400, description=f"StockNode {nid_i} doit être de type GROUP.")
        selected_qty = None
        if getattr(node, "unique_item", False):
            qty_raw = spec.get("quantity")
            if qty_raw is None:
                qty_val = getattr(node, "unique_quantity", None)
                if qty_val is None:
                    abort(400, description=f"Quantité requise pour le parent {node.name}.")
            else:
                try:
                    qty_val = int(qty_raw)
                except Exception:
                    abort(400, description=f"Quantité invalide pour le parent {node.name}.")
            if qty_val < 0:
                abort(400, description=f"Quantité négative pour le parent {node.name}.")
            max_qty = getattr(node, "unique_quantity", None)
            if max_qty is not None and qty_val > max_qty:
                abort(400, description=f"Quantité demandée supérieure au maximum ({max_qty}) pour {node.name}.")
            selected_qty = qty_val
        db.session.execute(
            event_stock.insert().values(
                event_id=ev.id,
                node_id=nid_i,
                selected_quantity=selected_qty,
            )
        )

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id, "url": f"/events/{ev.id}"}), 201


@bp_events.get("/list")
@login_required
def list_events():
    if not _can_view():
        abort(403)
    evs = Event.query.order_by(Event.created_at.desc()).all()
    return jsonify([
        {
            "id": e.id,
            "name": e.name,
            "status": getattr(e.status, "name", str(e.status)).upper(),
            "date": str(e.date) if e.date else None,
        }
        for e in evs
    ])


@bp_events.get("/<int:event_id>/tree")
@login_required
def event_tree(event_id: int):
    if not _can_view():
        abort(403)
    ev = _event_or_404(event_id)
    tree = build_event_tree(ev.id)
    return jsonify(tree)


@bp_events.post("/<int:event_id>/verify")
@login_required
def event_verify(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()  # "OK" | "NOT_OK" | "TODO"
    verifier_name = (payload.get("verifier_name") or current_user.username or "").strip()
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK", "TODO"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node or (node.type != NodeType.ITEM and not getattr(node, "unique_item", False)):
        abort(404, description="Item introuvable.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name or None,
        comment=comment,
    )
    db.session.add(rec)
    db.session.commit()

    _emit("event_update", {
        "type": "item_verified",
        "event_id": ev.id,
        "node_id": node.id,
        "status": status,
        "verifier_name": verifier_name or None,
        "comment": comment,
    })

    return jsonify({"ok": True})


@bp_events.post("/<int:event_id>/parent-status")
@login_required
def event_parent_charged(event_id: int):
    """Côté CHEF : marque un parent chargé / non chargé.
       Pas de migration : on sérialise nom de véhicule + opérateur dans comment (JSON).
    """
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle"))
    operator_name = (payload.get("operator_name") or current_user.username or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(404, description="Parent introuvable ou non GROUP.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node.id)

    ens.charged_vehicle = charged_vehicle
    # Sans migration : on range dans comment un JSON {"vehicle_name": "...", "operator_name": "..."}
    if charged_vehicle:
        ens.comment = json.dumps({
            "vehicle_name": vehicle_name,
            "operator_name": operator_name
        }, ensure_ascii=False)
    else:
        ens.comment = None

    ens.updated_at = datetime.utcnow()
    db.session.add(ens)
    db.session.commit()

    _emit("event_update", {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
        "vehicle_name": vehicle_name,
        "operator_name": operator_name,
    })

    return jsonify({"ok": True})


@bp_events.patch("/<int:event_id>/status")
@login_required
def event_set_status(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    data = request.get_json(silent=True) or {}
    status_raw = (data.get("status") or "").upper()
    if status_raw not in ("OPEN", "CLOSED"):
        abort(400, description="Statut invalide (OPEN | CLOSED).")

    ev.status = EventStatus.OPEN if status_raw == "OPEN" else EventStatus.CLOSED
    ev.updated_at = datetime.utcnow()
    db.session.commit()

    _emit("event_update", {"type": "status", "event_id": ev.id, "status": ev.status.name})
    return jsonify({"ok": True, "status": ev.status.name})


@bp_events.post("/<int:event_id>/share-link")
@login_required
def create_public_share_link(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    EventShareLink.query.filter_by(event_id=ev.id, active=True).update({"active": False})

    token = secrets.token_urlsafe(24)
    link = EventShareLink(event_id=ev.id, token=token, active=True)
    db.session.add(link)
    db.session.commit()

    return jsonify({"ok": True, "token": token, "url": f"/public/event/{token}"})


@bp_events.post("/<int:event_id>/delete")
@login_required
def delete_event(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    VerificationRecord.query.filter_by(event_id=ev.id).delete()
    EventNodeStatus.query.filter_by(event_id=ev.id).delete()
    EventShareLink.query.filter_by(event_id=ev.id).delete()
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)
    db.session.commit()

    return jsonify({"ok": True})

# -------------------------------------------------
# Public routes
# -------------------------------------------------
@bp_public.get("/event/<token>/tree")
def public_event_tree(token: str):
    ev = _event_from_token_or_404(token)
    tree = build_event_tree(ev.id)
    return jsonify(tree)

@bp_public.post("/event/<token>/verify")
def public_verify(token: str):
    ev = _event_from_token_or_404(token)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()  # "OK" | "NOT_OK" | "TODO"
    verifier_name = (payload.get("verifier_name") or "").strip()
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK", "TODO"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node or (node.type != NodeType.ITEM and not getattr(node, "unique_item", False)):
        abort(404, description="Élément introuvable ou non vérifiable.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name or None,
        comment=comment,
    )
    db.session.add(rec)
    db.session.commit()

    _emit("event_update", {
        "type": "public_verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": status,
        "verifier_name": verifier_name or None,
        "comment": comment,
    })
    return jsonify({"ok": True})


@bp_public.post("/event/<token>/charge")
def public_parent_charge(token: str):
    """Côté SECOURISTE (public) : marque un parent chargé/non chargé (fallback JSON dans comment)."""
    ev = _event_from_token_or_404(token)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle", True))
    operator_name = (payload.get("operator_name") or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(404, description="Parent introuvable ou non GROUP.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node.id)

    ens.charged_vehicle = charged_vehicle
    if charged_vehicle:
        ens.comment = json.dumps({
            "vehicle_name": vehicle_name,
            "operator_name": operator_name
        }, ensure_ascii=False)
    else:
        ens.comment = None

    ens.updated_at = datetime.utcnow()
    db.session.add(ens)
    db.session.commit()

    _emit("event_update", {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
        "vehicle_name": vehicle_name,
        "operator_name": operator_name,
    })

    return jsonify({"ok": True, "node_id": node.id, "vehicle": vehicle_name, "by": operator_name})
