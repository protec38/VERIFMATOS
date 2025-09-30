from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional
from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import select

from .. import db
from ..models import (
    Event,
    EventStatus,         # Enum OPEN / CLOSED pour l'événement
    EventShareLink,
    StockNode,
    NodeType,
    EventNodeStatus,     # Statut d'un nœud pendant l'événement
    event_stock,
    Role,
)

# ======================================================
# Blueprints
# ======================================================
bp_events = Blueprint("events_api", __name__, url_prefix="/events")
bp_public = Blueprint("public_api", __name__, url_prefix="/public")
bp = bp_events  # compat

# ======================================================
# Helpers d'authz
# ======================================================
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

# ======================================================
# Helpers statut ITEM (tolérant au schéma)
# ======================================================
def _as_status_name(val: Any) -> Optional[str]:
    """Retourne 'OK' / 'NOT_OK' / None pour diverses représentations."""
    if val is None:
        return None
    if hasattr(val, "name"):
        try:
            return str(val.name).upper()
        except Exception:
            pass
    if isinstance(val, bool):
        return "OK" if val else "NOT_OK"
    return str(val).upper()

def get_item_status(ens: EventNodeStatus) -> Optional[str]:
    """
    Lit le statut d'un ITEM pour un EventNodeStatus, quel que soit le champ utilisé en DB.
    Ordre de préférence : status -> result -> ok -> is_ok
    """
    if hasattr(ens, "status"):
        return _as_status_name(getattr(ens, "status"))
    if hasattr(ens, "result"):
        return _as_status_name(getattr(ens, "result"))
    if hasattr(ens, "ok"):
        return _as_status_name(bool(getattr(ens, "ok")))
    if hasattr(ens, "is_ok"):
        return _as_status_name(bool(getattr(ens, "is_ok")))
    return None

def set_item_status(ens: EventNodeStatus, status_str: str) -> None:
    """
    Écrit le statut 'OK' | 'NOT_OK' sur le champ disponible.
    S'il existe 'status' ou 'result' (string/enum), on écrit la chaîne.
    S'il n'y a qu'un booléen ('ok' / 'is_ok'), on mappe True/False.
    """
    status_str = (status_str or "").upper()
    value_bool = True if status_str == "OK" else False

    if hasattr(ens, "status"):
        setattr(ens, "status", status_str)
        return
    if hasattr(ens, "result"):
        setattr(ens, "result", status_str)
        return
    if hasattr(ens, "ok"):
        setattr(ens, "ok", value_bool)
        return
    if hasattr(ens, "is_ok"):
        setattr(ens, "is_ok", value_bool)
        return
    # sinon : on ne crée pas dynamiquement de colonne — on laisse silencieux.

def _emit(event: str, payload: Dict[str, Any]):
    # Hook optionnel (websocket/event-stream)
    try:
        pass
    except Exception:
        pass

def _all_items_ok(subtree: Dict[str, Any]) -> bool:
    has_item = False
    ok = True
    def rec(n: Dict[str, Any]):
        nonlocal has_item, ok
        if (n.get("type") or "").upper() == "ITEM":
            has_item = True
            ok = ok and ((n.get("last_status") or "").upper() == "OK")
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

# ======================================================
# Construction arbre d'inventaire pour un événement
# ======================================================
def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    rows = db.session.execute(
        select(StockNode).join(
            event_stock, StockNode.id == event_stock.c.node_id
        ).where(event_stock.c.event_id == event_id)
    ).scalars().all()

    roots = [n for n in rows if n.type == NodeType.GROUP]
    roots_ids = [r.id for r in roots]

    def serialize(node: StockNode) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": node.id,
            "name": node.name,
            "type": node.type.name,
            "children": []
        }
        if node.type == NodeType.ITEM:
            ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=node.id).first()
            if ens:
                out["last_status"] = get_item_status(ens)
                out["updated_at"] = ens.updated_at.isoformat() if getattr(ens, "updated_at", None) else None
                out["verifier_name"] = getattr(ens, "verifier_name", None)
                out["comment"] = getattr(ens, "comment", None)
                if hasattr(ens, "charged_vehicle"):
                    out["charged_vehicle"] = ens.charged_vehicle
                if hasattr(ens, "charged_vehicle_name"):
                    out["charged_vehicle_name"] = ens.charged_vehicle_name
        else:
            ch = StockNode.query.filter_by(parent_id=node.id).all()
            out["children"] = [serialize(c) for c in ch]
        return out

    return [serialize(r) for r in roots if r.id in roots_ids]

# ======================================================
# Routes internes (auth requise)
# ======================================================

@bp_events.post("/")
@bp_events.post("")  # accepte /events et /events/
@login_required
def create_event():
    if not _is_manager():
        abort(403)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    date_str = (data.get("date") or "").strip() or None
    root_ids = data.get("root_ids") or data.get("root_node_ids") or []

    if not name or not isinstance(root_ids, list) or not root_ids:
        abort(400, description="name et root_ids (liste non vide) requis.")

    date = None
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            abort(400, description="Format de date invalide (YYYY-MM-DD).")

    # created_by est une relation
    ev = Event(name=name, status=EventStatus.OPEN, date=date, created_by=current_user)
    db.session.add(ev)
    db.session.flush()

    seen = set()
    for nid in root_ids:
        try:
            nid_int = int(nid)
        except Exception:
            abort(400, description=f"root_id invalide: {nid}")
        if nid_int in seen:
            continue
        seen.add(nid_int)

        node = db.session.get(StockNode, nid_int)
        if not node:
            abort(400, description=f"StockNode {nid_int} introuvable.")
        if node.type != NodeType.GROUP:
            abort(400, description=f"StockNode {nid_int} doit être de type GROUP.")
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=nid_int))

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
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()  # "OK" | "NOT_OK"
    verifier_name = (payload.get("verifier_name") or current_user.username or "").strip()
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Élément introuvable.")
    if node.type != NodeType.ITEM:
        abort(400, description="Seuls les ITEM sont vérifiables directement.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node.id)
        db.session.add(ens)

    set_item_status(ens, status)
    ens.verifier_name = verifier_name or None
    ens.comment = comment
    ens.updated_at = datetime.utcnow()

    db.session.commit()

    _emit("event_update", {
        "type": "verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": get_item_status(ens),
        "verifier_name": ens.verifier_name,
        "comment": ens.comment,
    })
    return jsonify({"ok": True})

@bp_events.post("/<int:event_id>/parent-status")
@login_required
def event_parent_charged(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle"))
    operator_name = (payload.get("operator_name") or current_user.username or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Élément introuvable.")
    if node.type != NodeType.GROUP:
        abort(400, description="Seuls les GROUP peuvent être marqués comme chargés.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node.id)

    ens.charged_vehicle = charged_vehicle
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None
    ens.verifier_name = operator_name or None
    ens.updated_at = datetime.utcnow()

    db.session.add(ens)
    db.session.commit()

    out = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
    }
    if hasattr(ens, "charged_vehicle_name"):
        out["vehicle_name"] = ens.charged_vehicle_name
    _emit("event_update", out)
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
        abort(400, description="Statut invalide (OPEN ou CLOSED).")

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

    EventNodeStatus.query.filter_by(event_id=ev.id).delete()
    EventShareLink.query.filter_by(event_id=ev.id).delete()
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)
    db.session.commit()
    return jsonify({"ok": True})

def _status_is_open(ev: Event) -> bool:
    try:
        return ev.status == EventStatus.OPEN
    except Exception:
        return str(ev.status).upper() == "OPEN"

# ======================================================
# Routes publiques (pas d'auth)
# ======================================================
@bp_public.get("/event/<token>/tree")
def public_event_tree(token: str):
    ev = _event_from_token_or_404(token)
    tree = build_event_tree(ev.id)
    return jsonify(tree)

@bp_public.post("/event/<token>/verify")
def public_verify(token: str):
    ev = _event_from_token_or_404(token)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()
    verifier_name = (payload.get("verifier_name") or "")
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.ITEM:
        abort(404, description="Élément introuvable ou non vérifiable.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node.id)
        db.session.add(ens)

    set_item_status(ens, status)
    ens.verifier_name = verifier_name or None
    ens.updated_at = datetime.utcnow()
    ens.comment = comment

    db.session.commit()
    _emit("event_update", {
        "type": "public_verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": get_item_status(ens),
        "verifier_name": ens.verifier_name,
        "comment": ens.comment,
    })
    return jsonify({"ok": True})

@bp_public.post("/event/<token>/charge")
def public_parent_charge(token: str):
    ev = _event_from_token_or_404(token)
    if not _status_is_open(ev):
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle"))
    operator_name = (payload.get("operator_name") or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(404, description="Parent introuvable ou non GROUP.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first() \
        or EventNodeStatus(event_id=ev.id, node_id=node.id)
    ens.charged_vehicle = charged_vehicle
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None

    db.session.add(ens)
    db.session.commit()

    out = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": True,
    }
    if hasattr(ens, "charged_vehicle_name"):
        out["vehicle_name"] = ens.charged_vehicle_name
    _emit("event_update", out)
    return jsonify({"ok": True, "node_id": node.id, "vehicle": vehicle_name, "by": operator_name})
