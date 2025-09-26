# app/events/views.py
from __future__ import annotations
import uuid
from typing import Any, Dict
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user

from .. import db
from ..models import (
    Event, EventStatus, Role,
    StockNode, NodeType, event_stock,
    EventShareLink, EventNodeStatus, VerificationRecord,
)
from ..tree_query import build_event_tree

bp = Blueprint("events", __name__)

# --- helpers permissions ---
def _can_view(ev: Event) -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

def _can_manage(ev: Event) -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF) and ev.status == EventStatus.OPEN

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

def _enum_to_str(v):
    try:
        return v.name
    except Exception:
        return v

def _sanitize_tree(node: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": node.get("id"),
        "name": node.get("name"),
        "level": int(node.get("level", 0)),
        "type": _enum_to_str(node.get("type")) if not isinstance(node.get("type"), str) else node.get("type"),
        "quantity": node.get("quantity"),
        "last_status": None,
        "last_by": None,
        "charged_vehicle": node.get("charged_vehicle"),
        "children": [],
    }
    ls = node.get("last_status")
    if ls is not None:
        out["last_status"] = _enum_to_str(ls) if not isinstance(ls, str) else ls
    lb = node.get("last_by")
    if lb:
        out["last_by"] = lb
    for ch in (node.get("children") or []):
        out["children"].append(_sanitize_tree(ch))
    return out

# -------------------------
# Endpoints
# -------------------------

@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_view(ev):
        abort(403)
    raw = build_event_tree(event_id) or []
    tree = [_sanitize_tree(n) for n in raw]
    return jsonify(tree)

@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def get_event_stock_roots(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_view(ev):
        abort(403)
    q = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
    )
    roots = [{"id": n.id, "name": n.name} for n in q.all()]
    return jsonify(roots)

@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_manage(ev):
        abort(403)
    link = EventShareLink.query.filter_by(event_id=event_id, active=True).first()
    if not link:
        token = uuid.uuid4().hex
        link = EventShareLink(event_id=event_id, token=token, active=True)
        db.session.add(link)
        db.session.commit()
    return jsonify({"ok": True, "token": link.token, "url": f"/public/event/{link.token}"}), 201

@bp.patch("/events/<int:event_id>/status")
@login_required
def update_event_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    data = _json()
    status_str = (data.get("status") or "").upper()
    if status_str == "CLOSED":
        if not _can_manage(ev):
            abort(403)
        ev.status = EventStatus.CLOSED
        db.session.commit()
        return jsonify({"ok": True, "status": "CLOSED"})
    elif status_str == "OPEN":
        if current_user.role != Role.ADMIN:
            abort(403)
        ev.status = EventStatus.OPEN
        db.session.commit()
        return jsonify({"ok": True, "status": "OPEN"})
    abort(400, description="Statut invalide")

@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_manage(ev):
        abort(403)
    data = _json()
    node_id = int(data.get("node_id") or 0)
    charged = bool(data.get("charged_vehicle"))
    if not node_id:
        abort(400, description="node_id manquant")
    ens = (
        EventNodeStatus.query.filter_by(event_id=event_id, node_id=node_id).first()
        or EventNodeStatus(event_id=event_id, node_id=node_id)
    )
    ens.charged_vehicle = charged
    db.session.add(ens)
    db.session.commit()
    return jsonify({"ok": True, "node_id": node_id, "charged_vehicle": charged})

@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_manage(ev):
        abort(403)
    data = _json()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()
    # Fallback automatique pour chef/admin : on prend le nom du compte s'il manque
    verifier_name = (data.get("verifier_name") or "").strip()
    if not verifier_name and current_user.is_authenticated:
        verifier_name = getattr(current_user, "username", "") or "Chef de poste"

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name)")

    rec = VerificationRecord(
        event_id=event_id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name,
    )
    db.session.add(rec)
    db.session.commit()
    return jsonify({"ok": True, "record_id": rec.id})

@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    if not _can_view(ev):
        abort(403)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})
