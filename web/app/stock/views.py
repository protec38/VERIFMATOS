# app/stock/views.py — API hiérarchie de stock
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify, Response
from flask_login import login_required, current_user

from .. import db
from ..models import Role, NodeType, StockNode
from .service import (
    create_node,
    update_node,
    delete_node,
    duplicate_subtree,
    serialize_tree,
    list_roots,
)

bp = Blueprint("stock", __name__)

# -------------------------------------------------
# Droits
# -------------------------------------------------
def _can_read_stock() -> bool:
    # ✅ toute personne connectée peut LIRE (utile pour "Créer évènement")
    return current_user.is_authenticated

def _can_write_stock() -> bool:
    # ✍️ seules ces personnes peuvent MODIFIER
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

def _bad_request(msg: str, code: int = 400):
    return jsonify(error=msg), code

def _parse_node_type(x: str) -> NodeType:
    x = (x or "").strip().upper()
    if x not in ("GROUP", "ITEM"):
        raise ValueError("type must be GROUP or ITEM")
    return NodeType[x]

def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return date.fromisoformat(s)

# -------------------------------------------------
# ROOTS (lecture ouverte aux connectés)
# -------------------------------------------------
@bp.get("/stock/roots")
@login_required
def get_roots():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)
    roots = list_roots()
    return jsonify([
        {"id": r.id, "name": r.name, "type": r.type.name, "level": r.level}
        for r in roots
    ])

# -------------------------------------------------
# TREE (accepte id racine OU enfant, remonte à la racine) — lecture
# -------------------------------------------------
@bp.get("/stock/tree")
@login_required
def get_tree():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)
    try:
        node_id = int(request.args.get("root_id") or 0)
    except Exception:
        return _bad_request("root_id invalid")

    node = db.session.get(StockNode, node_id)
    if not node:
        return _bad_request("Root not found", 404)

    # si l'id n'est pas une racine, on remonte jusqu'à la vraie racine
    while node.parent_id is not None:
        node = node.parent

    return jsonify(serialize_tree(node))

# -------------------------------------------------
# CREATE (root ou enfant) — écriture
# -------------------------------------------------
@bp.post("/stock")
@login_required
def create_node_api():
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    type_str = (data.get("type") or "").strip()
    parent_id = data.get("parent_id")
    quantity = data.get("quantity")

    if not name:
        return _bad_request("name required")
    try:
        type_ = _parse_node_type(type_str)
        if parent_id is not None:
            parent_id = int(parent_id)
        if type_ == NodeType.ITEM:
            quantity = int(quantity or 0)
        else:
            quantity = None

        node = create_node(name=name, type_=type_, parent_id=parent_id, quantity=quantity)

        # expiry_date (ITEM)
        expiry = _parse_iso_date(data.get("expiry_date"))
        if type_ == NodeType.ITEM and expiry:
            node.expiry_date = expiry
            db.session.commit()

        return jsonify({
            "id": node.id, "name": node.name, "level": node.level, "type": node.type.name
        }), 201
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# UPDATE (rename, reparent, qty, expiry) — écriture
# -------------------------------------------------
@bp.patch("/stock/<int:node_id>")
@login_required
def update_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    try:
        node = db.session.get(StockNode, node_id)
        if not node:
            return _bad_request("Not found", 404)

        name = (data.get("name") or node.name).strip()
        parent_id = data.get("parent_id", node.parent_id)
        if parent_id is not None:
            parent_id = int(parent_id)

        # qty only for ITEM
        qty = data.get("quantity", node.quantity)
        if node.type == NodeType.ITEM and qty is not None:
            qty = int(qty)
        else:
            qty = None if node.type != NodeType.ITEM else node.quantity

        update_node(node_id=node_id, name=name, parent_id=parent_id, quantity=qty)

        # expiry_date (ITEM uniquement)
        if node.type == NodeType.ITEM and "expiry_date" in data:
            node.expiry_date = _parse_iso_date(data.get("expiry_date"))
            db.session.commit()

        node = db.session.get(StockNode, node_id)  # refresh
        return jsonify({
            "id": node.id, "name": node.name, "level": node.level, "type": node.type.name
        })
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# DELETE (subtree) — écriture
# -------------------------------------------------
@bp.delete("/stock/<int:node_id>")
@login_required
def delete_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)
    try:
        delete_node(node_id)
        return jsonify({"ok": True})
    except LookupError:
        return _bad_request("Not found", 404)
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# DUPLICATE SUBTREE — écriture
# -------------------------------------------------
@bp.post("/stock/<int:node_id>/duplicate")
@login_required
def duplicate_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    new_name = (data.get("new_name") or "").strip()
    new_parent_id = data.get("new_parent_id")
    if not new_name:
        return _bad_request("new_name required")
    try:
        new_root = duplicate_subtree(node_id, new_name=new_name, new_parent_id=new_parent_id)
        return jsonify(
            {"id": new_root.id, "name": new_root.name, "level": new_root.level, "type": new_root.type.name}
        ), 201
    except LookupError:
        return _bad_request("Not found", 404)
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# EXPORT (JSON) — lecture
# -------------------------------------------------
@bp.get("/stock/export.json")
@login_required
def export_stock_json():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)

    roots = list_roots()

    def _serialize_tree_full(n: StockNode) -> Dict[str, Any]:
        out = {
            "name": n.name,
            "type": n.type.name,
            "quantity": n.quantity if n.type == NodeType.ITEM else None,
            "expiry_date": n.expiry_date.isoformat() if getattr(n, "expiry_date", None) else None,
            "children": [],
        }
        for c in sorted(n.children, key=lambda x: (x.level, x.id)):
            out["children"].append(_serialize_tree_full(c))
        return out

    payload = {
        "version": "1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "roots": [_serialize_tree_full(r) for r in roots],
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stock_export.json"'},
    )

# -------------------------------------------------
# IMPORT (JSON) — écriture
# -------------------------------------------------
@bp.post("/stock/import")
@login_required
def import_stock():
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    mode = (request.args.get("mode") or request.form.get("mode") or "merge").lower().strip()

    # Récup JSON via file upload OU via body JSON
    data_obj: Optional[Dict[str, Any]] = None
    if "file" in request.files:
        try:
            data_obj = json.load(request.files["file"].stream)
        except Exception:
            return _bad_request("Invalid JSON file")
    else:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            data_obj = payload
        elif isinstance(payload, list):
            data_obj = {"roots": payload}
        else:
            return _bad_request("JSON body expected")

    roots = data_obj.get("roots")
    if roots is None:
        return _bad_request("Missing 'roots' array")

    if mode not in ("merge", "replace"):
        return _bad_request("mode must be 'merge' or 'replace'")

    try:
        if mode == "replace":
            # suppression complète du stock
            all_nodes = db.session.query(StockNode).all()
            for n in reversed(all_nodes):
                db.session.delete(n)
            db.session.commit()

        def create_subtree(parent_id: Optional[int], node_dict: Dict[str, Any]) -> StockNode:
            name = (node_dict.get("name") or "").strip()
            if not name:
                raise ValueError("node name required")
            type_ = _parse_node_type(node_dict.get("type"))
            quantity = None
            if type_ == NodeType.ITEM:
                quantity = int(node_dict.get("quantity") or 0)
            node = create_node(name=name, type_=type_, parent_id=parent_id, quantity=quantity)

            # expiry_date (ITEM)
            if type_ == NodeType.ITEM and node_dict.get("expiry_date"):
                node.expiry_date = _parse_iso_date(node_dict.get("expiry_date"))
                db.session.flush()

            for c in node_dict.get("children") or []:
                create_subtree(node.id, c)
            return node

        created_ids: List[int] = []
        for r in roots:
            new_root = create_subtree(None, r)
            created_ids.append(new_root.id)
        db.session.commit()

        return jsonify({"ok": True, "created_roots": created_ids, "mode": mode})
    except Exception as e:
        db.session.rollback()
        return _bad_request(str(e))

# -------------------------------------------------
# Stats péremptions — lecture
# -------------------------------------------------
@bp.get("/stats/stock/expiry/counts")
@login_required
def expiry_counts():
    if not _can_read_stock():
        return jsonify({"expired": 0, "j30": 0})

    items = db.session.query(StockNode).filter(
        StockNode.type == NodeType.ITEM,
        StockNode.expiry_date.isnot(None)
    ).all()

    from datetime import date as _date
    today = _date.today()
    expired = 0
    j30 = 0
    for it in items:
        ex = getattr(it, "expiry_date", None)
        if not ex:
            continue
        delta = (ex - today).days
        if delta < 0:
            expired += 1
        elif delta <= 30:
            j30 += 1

    return jsonify({"expired": expired, "j30": j30})
