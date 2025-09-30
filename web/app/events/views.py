from __future__ import annotations

import secrets
from typing import Any, Dict, List
from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import select

from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    StockNode,
    NodeType,
    EventNodeStatus,
    event_stock,
    Role,
)

# ======================
# Blueprints STABLES
# ======================
bp_events = Blueprint("events_api", __name__, url_prefix="/events")
bp_public = Blueprint("public_api", __name__, url_prefix="/public")

# Pour compat avec anciens imports
bp = bp_events


# -----------------------------
# Helpers
# -----------------------------
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


def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    """Construit l’arbre pour l’événement."""
    # 1) récupère les racines attachées à l’événement
    rows = db.session.execute(select(StockNode).join(
        event_stock, StockNode.id == event_stock.c.node_id
    ).where(event_stock.c.event_id == event_id)).scalars().all()

    # on ne garde que les GROUP comme racines
    roots = [n for n in rows if n.type == NodeType.GROUP]
    roots_ids = [r.id for r in roots]

    # 2) pour chaque racine, construire récursivement (GROUP -> ITEM)
    def serialize(node: StockNode) -> Dict[str, Any]:
        out = {
            "id": node.id,
            "name": node.name,
            "type": node.type.name,
            "children": []
        }
        # statut dernier known si ITEM
        if node.type == NodeType.ITEM:
            ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=node.id).first()
            if ens:
                out["last_status"] = (ens.status.name if ens.status else None)
                out["updated_at"] = ens.updated_at.isoformat() if ens.updated_at else None
                out["verifier_name"] = ens.verifier_name
                out["comment"] = ens.comment
                # propriétés optionnelles
                if hasattr(ens, "charged_vehicle"):
                    out["charged_vehicle"] = ens.charged_vehicle
                if hasattr(ens, "charged_vehicle_name"):
                    out["charged_vehicle_name"] = ens.charged_vehicle_name
        else:
            # enfants
            ch = StockNode.query.filter_by(parent_id=node.id).all()
            out["children"] = [serialize(c) for c in ch]
        return out

    return [serialize(r) for r in roots if r.id in roots_ids]


def _emit(event: str, payload: Dict[str, Any]):
    """Placeholder pour du websocket/event-stream si besoin."""
    try:
        # hook si existant
        pass
    except Exception:
        pass

def _all_items_ok(subtree: Dict[str, Any]) -> bool:
    has_item = False
    ok = True

    def rec(n: Dict[str, Any]):
        nonlocal has_item, ok
        ntype = (n.get("type") or "").upper()
        if ntype == "ITEM":
            has_item = True
            last = (n.get("last_status") or "").upper()
            ok = ok and (last == "OK")
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


# ============================================
# ÉVÉNEMENT (INTERNE — nécessite authentifié)
# ============================================

@bp_events.post("/")
@bp_events.post("")
@login_required
def create_event():
    """Créer un événement + attacher les parents racines (GROUP)."""
    if not _is_manager():
        abort(403)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    date_str = (data.get("date") or "").strip() or None
    root_ids = data.get("root_ids") or data.get("root_node_ids") or []

    if not name or not isinstance(root_ids, list) or not root_ids:
        abort(400, description="name et root_ids (liste non vide) requis.")

    # date optionnelle (YYYY-MM-DD)
    date = None
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            abort(400, description="Format de date invalide (attendu YYYY-MM-DD).")

    # création event
    ev = Event(name=name, status=EventStatus.OPEN, date=date, created_by=current_user.id)
    db.session.add(ev)
    db.session.flush()

    # attache les racines
    seen = set()
    for nid in root_ids:
        try:
            nid = int(nid)
        except Exception:
            abort(400, description=f"root_id invalide: {nid}")
        if nid in seen:
            continue
        seen.add(nid)

        node = db.session.get(StockNode, nid)
        if not node:
            abort(400, description=f"StockNode {nid} introuvable.")
        if node.type != NodeType.GROUP:
            abort(400, description=f"StockNode {nid} doit être de type GROUP.")
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=nid))

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id, "url": f"/events/{ev.id}"}), 201


@bp_events.get("/list")
@login_required
def list_events():
    """Lister tous les événements (dashboard)."""
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
    status = (payload.get("status") or "").upper()
    verifier_name = (payload.get("verifier_name") or current_user.username or "").strip()

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

    ens.status = EventStatus.OK if status == "OK" else EventStatus.NOT_OK
    ens.verifier_name = verifier_name or None
    ens.updated_at = datetime.utcnow()

    # commentaire optionnel
    comment = (payload.get("comment") or "").strip() or None
    ens.comment = comment

    db.session.commit()

    # émettre un petit signal pour front (si websocket)
    _emit("event_update", {
        "type": "verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": ens.status.name,
        "verifier_name": ens.verifier_name,
        "comment": ens.comment,
    })

    return jsonify({"ok": True})


@bp_events.post("/<int:event_id>/parent-status")
@login_required
def event_parent_charged(event_id: int):
    """Marquer un parent (GROUP) comme « chargé » pour un véhicule."""
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
    ens.updated_at = datetime.utcnow()
    ens.verifier_name = operator_name or None
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None

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

    # on désactive les anciens liens actifs
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

    # supprime les statuts
    EventNodeStatus.query.filter_by(event_id=ev.id).delete()
    # supprime les liens partagés
    EventShareLink.query.filter_by(event_id=ev.id).delete()
    # détache les roots
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    # enfin supprime l'événement
    db.session.delete(ev)
    db.session.commit()

    return jsonify({"ok": True})


def _status_is_open(ev: Event) -> bool:
    try:
        return ev.status == EventStatus.OPEN
    except Exception:
        # si enum différent
        return str(ev.status).upper() == "OPEN"


# ============================================
# PUBLIC (pas d’authentification)
# ============================================

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

    ens.status = EventStatus.OK if status == "OK" else EventStatus.NOT_OK
    ens.verifier_name = verifier_name or None
    ens.updated_at = datetime.utcnow()
    ens.comment = comment

    db.session.commit()
    _emit("event_update", {
        "type": "public_verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": ens.status.name,
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
