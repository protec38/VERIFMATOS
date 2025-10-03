from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from .. import db
from ..models import ReassortBatch, ReassortItem, Role, StockNode

bp = Blueprint("reassort", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _can_manage() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)


def _require_manage() -> None:
    if not _can_manage():
        abort(403)


def _json_payload() -> Dict[str, Any]:
    if not request.is_json:
        abort(400, description="JSON requis")
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        abort(400, description="JSON invalide")
    return data


def _serialize_batch(batch: ReassortBatch) -> Dict[str, Any]:
    return {
        "id": batch.id,
        "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
        "quantity": batch.quantity,
        "lot": batch.lot,
        "note": batch.note,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _sorted_batches(item: ReassortItem) -> List[ReassortBatch]:
    batches = list(item.batches.all()) if hasattr(item.batches, "all") else list(item.batches)
    batches.sort(key=lambda b: (
        b.expiry_date is None,
        b.expiry_date or date.max,
        b.id,
    ))
    return batches


def _serialize_item(item: ReassortItem) -> Dict[str, Any]:
    batches = _sorted_batches(item)
    total_qty = sum(b.quantity or 0 for b in batches)
    return {
        "id": item.id,
        "name": item.name,
        "note": item.note,
        "target_node_id": item.target_node_id,
        "target_node_name": item.target_node.name if item.target_node else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "total_quantity": total_qty,
        "batches": [_serialize_batch(b) for b in batches],
    }


# ---------------------------------------------------------------------------
# Page HTML
# ---------------------------------------------------------------------------


@bp.get("/reassort")
@login_required
def reassort_page():
    _require_manage()
    return render_template("reassort.html")


# ---------------------------------------------------------------------------
# API CRUD
# ---------------------------------------------------------------------------


@bp.get("/reassort/api/items")
@login_required
def api_list_items():
    _require_manage()
    items = ReassortItem.query.order_by(ReassortItem.name.asc()).all()
    return jsonify([_serialize_item(it) for it in items])


@bp.post("/reassort/api/items")
@login_required
def api_create_item():
    _require_manage()
    data = _json_payload()
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, description="Nom requis")

    note = (data.get("note") or "").strip() or None
    target_id = data.get("target_node_id")
    target_node = None
    if target_id not in (None, ""):
        try:
            target_id_int = int(target_id)
        except Exception:
            abort(400, description="Identifiant de stock invalide")
        target_node = db.session.get(StockNode, target_id_int)
        if not target_node:
            abort(404, description="Stock introuvable")

    item = ReassortItem(name=name, note=note, target_node=target_node)
    db.session.add(item)
    db.session.commit()
    return jsonify(_serialize_item(item)), 201


@bp.patch("/reassort/api/items/<int:item_id>")
@login_required
def api_update_item(item_id: int):
    _require_manage()
    item = db.session.get(ReassortItem, item_id)
    if not item:
        abort(404, description="Article introuvable")

    data = _json_payload()

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            abort(400, description="Nom requis")
        item.name = name

    if "note" in data:
        item.note = (data.get("note") or "").strip() or None

    if "target_node_id" in data:
        raw = data.get("target_node_id")
        if raw in (None, ""):
            item.target_node = None
        else:
            try:
                target_id = int(raw)
            except Exception:
                abort(400, description="Identifiant de stock invalide")
            node = db.session.get(StockNode, target_id)
            if not node:
                abort(404, description="Stock introuvable")
            item.target_node = node

    item.updated_at = datetime.utcnow()
    db.session.add(item)
    db.session.commit()
    return jsonify(_serialize_item(item))


@bp.delete("/reassort/api/items/<int:item_id>")
@login_required
def api_delete_item(item_id: int):
    _require_manage()
    item = db.session.get(ReassortItem, item_id)
    if not item:
        abort(404, description="Article introuvable")
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/reassort/api/items/<int:item_id>/batches")
@login_required
def api_create_batch(item_id: int):
    _require_manage()
    item = db.session.get(ReassortItem, item_id)
    if not item:
        abort(404, description="Article introuvable")

    data = _json_payload()

    try:
        quantity = int(data.get("quantity", 0))
    except Exception:
        abort(400, description="Quantité invalide")
    if quantity < 0:
        abort(400, description="Quantité négative")

    expiry_raw = (data.get("expiry_date") or "").strip()
    expiry_value = None
    if expiry_raw:
        try:
            expiry_value = date.fromisoformat(expiry_raw)
        except Exception:
            abort(400, description="Date de péremption invalide")

    batch = ReassortBatch(
        item=item,
        quantity=quantity,
        expiry_date=expiry_value,
        lot=(data.get("lot") or "").strip() or None,
        note=(data.get("note") or "").strip() or None,
    )
    db.session.add(batch)
    db.session.commit()
    return jsonify(_serialize_item(item)), 201


@bp.patch("/reassort/api/batches/<int:batch_id>")
@login_required
def api_update_batch(batch_id: int):
    _require_manage()
    batch = db.session.get(ReassortBatch, batch_id)
    if not batch:
        abort(404, description="Lot introuvable")

    data = _json_payload()

    if "quantity" in data:
        try:
            quantity = int(data.get("quantity"))
        except Exception:
            abort(400, description="Quantité invalide")
        if quantity < 0:
            abort(400, description="Quantité négative")
        batch.quantity = quantity

    if "expiry_date" in data:
        expiry_raw = (data.get("expiry_date") or "").strip()
        if not expiry_raw:
            batch.expiry_date = None
        else:
            try:
                batch.expiry_date = date.fromisoformat(expiry_raw)
            except Exception:
                abort(400, description="Date de péremption invalide")

    if "lot" in data:
        batch.lot = (data.get("lot") or "").strip() or None

    if "note" in data:
        batch.note = (data.get("note") or "").strip() or None

    batch.updated_at = datetime.utcnow()
    db.session.add(batch)
    db.session.commit()
    return jsonify(_serialize_item(batch.item))


@bp.delete("/reassort/api/batches/<int:batch_id>")
@login_required
def api_delete_batch(batch_id: int):
    _require_manage()
    batch = db.session.get(ReassortBatch, batch_id)
    if not batch:
        abort(404, description="Lot introuvable")
    item = batch.item
    db.session.delete(batch)
    db.session.commit()
    return jsonify(_serialize_item(item))
