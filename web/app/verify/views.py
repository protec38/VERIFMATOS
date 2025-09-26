# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict
from flask import Blueprint, jsonify, request, abort, render_template
from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    VerificationRecord,
    StockNode,
)
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

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

def _sanitize_tree(node):
    out = {
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

@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id) or []
    tree = [_sanitize_tree(n) for n in tree]
    return render_template("public_event.html", token=token, event=ev, tree=tree)

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree = build_event_tree(ev.id) or []
    tree = [_sanitize_tree(n) for n in tree]
    return jsonify(tree)

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

    return jsonify({"ok": True, "record_id": rec.id})
