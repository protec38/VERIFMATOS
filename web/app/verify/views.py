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
    StockItemExpiry,
    ReassortBatch,
    ReassortItem,
)
from ..tree_query import build_event_tree
from sqlalchemy import or_
from datetime import date, datetime

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


def _ensure_reassort_tables() -> None:
    try:
        ReassortItem.__table__.create(bind=db.engine, checkfirst=True)
        ReassortBatch.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _ensure_expiry_table() -> None:
    try:
        StockItemExpiry.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

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
                 issue_code?:"broken"|"missing"|"other", observed_qty?:int, missing_qty?:int,
                 expiry_id?:int, expiry_date?:"YYYY-MM-DD" }
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

    expiry_id: Optional[int] = None
    expiry_date: Optional[date] = None
    if "expiry_id" in data and data.get("expiry_id") not in (None, ""):
        try:
            expiry_id = int(data.get("expiry_id"))
        except Exception:
            abort(400, description="expiry_id invalide")
    if "expiry_date" in data and data.get("expiry_date"):
        try:
            expiry_date = date.fromisoformat(str(data.get("expiry_date")))
        except Exception:
            abort(400, description="expiry_date invalide")

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

    # item ou lot (lié à un item)
    node = db.session.get(StockNode, node_id) if node_id else None

    expiry: Optional[StockItemExpiry] = None
    if expiry_id or expiry_date:
        _ensure_expiry_table()
        if expiry_id:
            expiry = db.session.get(StockItemExpiry, expiry_id)
            if not expiry:
                abort(404, description="Lot introuvable")
        if expiry is None and node_id and expiry_date:
            expiry = (
                StockItemExpiry.query
                .filter_by(node_id=node_id, expiry_date=expiry_date)
                .order_by(StockItemExpiry.id.asc())
                .first()
            )
        if expiry is None and expiry_id:
            abort(404, description="Lot introuvable")
        if node is None:
            source_node_id = expiry.node_id if expiry else node_id
            node = db.session.get(StockNode, source_node_id) if source_node_id else None
            node_id = node.id if node else None
        elif expiry and expiry.node_id != node.id:
            abort(400, description="Ce lot n'appartient pas à l'objet indiqué")

    if not node:
        abort(404, description="Item introuvable")
    if node.type != NodeType.ITEM and not getattr(node, "unique_item", False):
        abort(400, description="Seuls les items (feuilles) sont vérifiables")

    # optionnels
    comment = (data.get("comment") or "").strip() or None
    if expiry is not None:
        parts = []
        if expiry.lot:
            parts.append(f"Lot {expiry.lot}")
        if expiry.expiry_date:
            parts.append(f"péremption {expiry.expiry_date.isoformat()}")
        if expiry.note:
            parts.append(expiry.note)
        lot_label = " | ".join(parts) or f"Lot #{expiry.id}"
        comment = f"{lot_label} | {comment}" if comment else lot_label
    elif expiry_date is not None:
        exp_label = expiry_date.isoformat()
        comment = f"Péremption {exp_label} | {comment}" if comment else f"Péremption {exp_label}"

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


def _sync_item_expiry(node_id: int) -> Optional[date]:
    try:
        _ensure_expiry_table()
        rows: List[StockItemExpiry] = (
            StockItemExpiry.query
            .filter_by(node_id=node_id)
            .order_by(StockItemExpiry.expiry_date.asc(), StockItemExpiry.id.asc())
            .all()
        )
    except Exception:
        db.session.rollback()
        return None
    next_date = rows[0].expiry_date if rows else None
    node = db.session.get(StockNode, node_id)
    if node is not None:
        node.expiry_date = next_date
        db.session.add(node)
    return next_date


def _serialize_reassort_batch(batch: ReassortBatch, node_id: int) -> Dict[str, Any]:
    preferred = batch.item.target_node_id == node_id if batch.item else False
    return {
        "batch_id": batch.id,
        "item_id": batch.item_id,
        "item_name": batch.item.name if batch.item else None,
        "quantity": batch.quantity,
        "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
        "lot": batch.lot,
        "note": batch.note,
        "preferred": preferred,
    }


@bp.get("/public/event/<token>/reassort/<int:node_id>")
def public_reassort_options(token: str, node_id: int):
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)

    _ensure_reassort_tables()

    batches = (
        ReassortBatch.query
        .join(ReassortItem)
        .filter(ReassortBatch.quantity > 0)
        .filter(or_(ReassortItem.target_node_id == node_id, ReassortItem.target_node_id.is_(None)))
        .all()
    )
    batches.sort(key=lambda b: (
        b.item.target_node_id != node_id if b.item else True,
        (b.item.name.lower() if b.item and b.item.name else ""),
        b.expiry_date or date.max,
        b.id,
    ))

    payload = [_serialize_reassort_batch(b, node_id) for b in batches]
    return jsonify({
        "node_id": node_id,
        "items": payload,
    })


@bp.post("/public/event/<token>/replace")
def public_replace_from_reassort(token: str):
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

    try:
        batch_id = int(data.get("batch_id") or 0)
    except Exception:
        abort(400, description="batch_id invalide")

    try:
        quantity = int(data.get("quantity") or 1)
    except Exception:
        quantity = 1
    if quantity <= 0:
        quantity = 1

    verifier_name = (data.get("verifier_name") or "").strip()
    if not verifier_name:
        abort(400, description="Nom du vérificateur requis")

    comment_extra = (data.get("comment") or "").strip() or None

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Item introuvable")
    if node.type != NodeType.ITEM and not getattr(node, "unique_item", False):
        abort(400, description="Seuls les items peuvent être remplacés")

    _ensure_reassort_tables()
    batch = db.session.get(ReassortBatch, batch_id)
    if not batch or batch.quantity <= 0:
        abort(404, description="Lot de réassort indisponible")

    if batch.item and batch.item.target_node_id not in (None, node_id):
        # On autorise tout de même mais on diminue la priorité si mismatch
        pass

    use_qty = min(quantity, batch.quantity)
    batch.quantity -= use_qty
    batch.updated_at = datetime.utcnow()
    db.session.add(batch)

    removed_expiry: Optional[date] = None
    expiry_id = data.get("expiry_id")
    expiry_date_raw = data.get("expiry_date")

    _ensure_expiry_table()

    if expiry_id:
        try:
            exp = db.session.get(StockItemExpiry, int(expiry_id))
        except Exception:
            exp = None
        if exp and exp.node_id == node_id:
            if exp.quantity and exp.quantity > use_qty:
                exp.quantity -= use_qty
                removed_expiry = exp.expiry_date
                db.session.add(exp)
            else:
                removed_expiry = exp.expiry_date
                db.session.delete(exp)
    elif expiry_date_raw:
        try:
            exp_date = date.fromisoformat(str(expiry_date_raw))
        except Exception:
            exp_date = None
        if exp_date is not None:
            exp = (
                StockItemExpiry.query
                .filter_by(node_id=node_id, expiry_date=exp_date)
                .order_by(StockItemExpiry.id.asc())
                .first()
            )
            if exp:
                if exp.quantity and exp.quantity > use_qty:
                    exp.quantity -= use_qty
                    removed_expiry = exp.expiry_date
                    db.session.add(exp)
                else:
                    removed_expiry = exp.expiry_date
                    db.session.delete(exp)

    new_expiry = batch.expiry_date
    if new_expiry:
        entry = StockItemExpiry(
            node_id=node_id,
            expiry_date=new_expiry,
            quantity=use_qty,
            lot=batch.lot,
            note=batch.note,
        )
        db.session.add(entry)
    elif node.expiry_date and removed_expiry and node.expiry_date == removed_expiry:
        node.expiry_date = None

    next_date = _sync_item_expiry(node_id)
    if next_date is None and new_expiry:
        node.expiry_date = new_expiry
        db.session.add(node)

    parts = ["Remplacement via réassort"]
    if batch.item and batch.item.name:
        parts.append(f"Article: {batch.item.name}")
    if batch.lot:
        parts.append(f"Lot réassort: {batch.lot}")
    if removed_expiry:
        parts.append(f"Lot retiré: {removed_expiry.isoformat()}")
    if new_expiry:
        parts.append(f"Nouvelle exp.: {new_expiry.isoformat()}")
    if use_qty > 1:
        parts.append(f"Quantité: {use_qty}")
    if comment_extra:
        parts.append(comment_extra)
    final_comment = " | ".join(parts)

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=ItemStatus.OK,
        verifier_name=verifier_name,
        comment=final_comment,
    )
    db.session.add(rec)

    db.session.commit()

    return jsonify({
        "ok": True,
        "node_id": node_id,
        "batch_id": batch_id,
        "quantity": use_qty,
        "new_expiry": new_expiry.isoformat() if new_expiry else None,
        "remaining_batch": batch.quantity,
    })
