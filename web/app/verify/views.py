# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from flask import Blueprint, jsonify, request, abort, render_template

from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    VerificationRecord,
    StockNode,
    ItemStatus,
    IssueCode,
    EventNodeStatus,
    NodeType,
)
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

# --------- utils JSON / sanit ---------
def _json() -> Dict[str, Any]:
    if not request.is_json:
        abort(400, description="Payload JSON attendu")
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        abort(400, description="JSON invalide")
    return data

def _sanitize_tree(node: Dict[str, Any]) -> Dict[str, Any]:
    # build_event_tree renvoie déjà des objets JSON-safe
    return node

# --------- pages publiques ---------
@bp.get("/public/event/<token>")
def public_event_page(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        # page visible même si fermé, mais en lecture seule
        readonly = True
    else:
        readonly = False

    tree = [ _sanitize_tree(t) for t in (build_event_tree(ev.id) or []) ]
    return render_template("public_event.html", token=token, event=ev, tree=tree, readonly=readonly)

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree: List[dict] = build_event_tree(ev.id) or []
    tree = [_sanitize_tree(n) for n in tree]
    return jsonify(tree)

# --------- vérif publique (ITEM) ---------
@bp.post("/public/event/<token>/verify")
def public_verify_item(token: str):
    """
    Enregistre une vérification d’ITEM.
    Body JSON: { node_id:int, status:"ok"|"not_ok"|"todo", verifier_name:str, comment?:str,
                 issue_code?:"broken"|"missing"|"other", observed_qty?:int, missing_qty?:int }
    """
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
        abort(400, description="node_id invalide")

    # status
    status_map = {"ok": ItemStatus.OK, "not_ok": ItemStatus.NOT_OK, "todo": ItemStatus.TODO}
    status_str = (data.get("status") or "").strip().lower()
    if status_str not in status_map:
        abort(400, description="status doit être ok | not_ok | todo")
    status = status_map[status_str]

    # verifier_name
    verifier_name = (data.get("verifier_name") or "").strip()
    if not verifier_name:
        abort(400, description="Nom du vérificateur requis")

    # item
    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Item introuvable")
    if getattr(node.type, "name", None) != "ITEM":
        abort(400, description="Seuls les items (feuilles) sont vérifiables")

    # optionnels
    comment = (data.get("comment") or "").strip() or None

    issue_code = None
    if "issue_code" in data and data["issue_code"]:
        ic = str(data["issue_code"]).strip().upper()
        # tolérant: accepte enum.name / string
        if hasattr(IssueCode, ic):
            issue_code = getattr(IssueCode, ic)
        else:
            issue_code = ic

    def _safe_int(v):
        try:
            i = int(v)
            return i if i >= 0 else 0
        except Exception:
            return None

    observed_qty = _safe_int(data.get("observed_qty"))
    missing_qty = _safe_int(data.get("missing_qty"))

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name,
        comment=comment,
        issue_code=issue_code,
        observed_qty=observed_qty,
        missing_qty=missing_qty,
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "record_id": rec.id})

# --------- marquer un parent (racine) chargé ----------
@bp.post("/public/event/<token>/charge")
def public_mark_group_charged(token: str):
    """
    Marque un parent RACINE comme “chargé”.
    Body JSON: { node_id:int, vehicle_name?:str, operator_name?:str }
    """
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
        abort(400, description="node_id invalide")

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Parent introuvable")
    if getattr(node.type, "name", None) != "GROUP":
        abort(400, description="Seuls les parents (GROUP) sont chargeables")

    vehicle = (data.get("vehicle_name") or "").strip() or None
    operator_name = (data.get("operator_name") or "").strip() or None

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node_id).first()
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node_id)
    ens.charged_vehicle = True
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle

    # commentaire synthétique (optionnel)
    parts = []
    if vehicle:
        parts.append(f"Véhicule: {vehicle}")
    if operator_name:
        parts.append(f"Par: {operator_name}")
    if parts:
        ens.comment = " | ".join(parts)

    db.session.add(ens)
    db.session.commit()

    return jsonify({
        "ok": True,
        "event_id": ev.id,
        "node_id": node_id,
        "charged_vehicle": True,
        "comment": getattr(ens, "comment", None),
        "updated_at": getattr(ens, "updated_at", None).isoformat() if getattr(ens, "updated_at", None) else None,
    })
