# app/stock/views.py — API CRUD hiérarchie de stock (ADMIN only)
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
# Helpers & droits
# -------------------------------------------------
def require_admin() -> bool:
    return current_user.is_authenticated and current_user.role == Role.ADMIN

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

# --- sérialisation avec péremption (pour l’export) ---
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

# -------------------------------------------------
# LIST ROOTS
# -------------------------------------------------
@bp.get("/stock/roots")
@login_required
def get_roots():
    if not require_admin():
        return _bad_request("Forbidden", 403)
    roots = list_roots()
    return jsonify([
        {"id": r.id, "name": r.name, "type": r.type.name, "level": r.level}
        for r in roots
    ])

# -------------------------------------------------
# READ TREE (par racine)
# -------------------------------------------------
@bp.get("/stock/tree")
@login_required
def get_tree():
    if not require_admin():
        return _bad_request("Forbidden", 403)
    try:
        root_id = int(request.args.get("root_id") or 0)
    except Exception:
        return _bad_request("root_id invalid")
    root = db.session.get(StockNode, root_id)
    if not root or root.parent_id is not None:
        return _bad_request("Root not found", 404)
    return jsonify(serialize_tree(root))

# -------------------------------------------------
# CREATE NODE (root ou enfant)
# -------------------------------------------------
@bp.post("/stock")
@login_required
def create_node_api():
    if not require_admin():
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
        # Si ITEM: prise en charge éventuelle d'une péremption
        expiry = _parse_iso_date(data.get("expiry_date"))
        if type_ == NodeType.ITEM and expiry:
            node.expiry_date = expiry
            db.session.commit()
        return jsonify({"id": node.id, "name": node.name, "level": node.level, "type": node.type.name}), 201
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# UPDATE NODE (rename, reparent, qty, expiry)
# -------------------------------------------------
@bp.patch("/stock/<int:node_id>")
@login_required
def update_node_api(node_id: int):
    if not require_admin():
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

        # ✅ correction: pas de '*' dans l'appel
        update_node(node_id=node_id, name=name, parent_id=parent_id, quantity=qty)

        # expiry_date (ITEM uniquement)
        if node.type == NodeType.ITEM and "expiry_date" in data:
            node.expiry_date = _parse_iso_date(data.get("expiry_date"))
            db.session.commit()

        node = db.session.get(StockNode, node_id)  # refresh
        return jsonify({"id": node.id, "name": node.name, "level": node.level, "type": node.type.name})
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# DELETE NODE (subtree)
# -------------------------------------------------
@bp.delete("/stock/<int:node_id>")
@login_required
def delete_node_api(node_id: int):
    if not require_admin():
        return _bad_request("Forbidden", 403)
    try:
        delete_node(node_id)
        return jsonify({"ok": True})
    except LookupError:
        return _bad_request("Not found", 404)
    except Exception as e:
        return _bad_request(str(e))

# -------------------------------------------------
# DUPLICATE SUBTREE
# -------------------------------------------------
@bp.post("/stock/<int:node_id>/duplicate")
@login_required
def duplicate_node_api(node_id: int):
    if not require_admin():
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
# EXPORT (JSON) — toutes les racines
# -------------------------------------------------
@bp.get("/stock/export.json")
@login_required
def export_stock_json():
    if not require_admin():
        return _bad_request("Forbidden", 403)
    roots = list_roots()
    payload = {
        "version": "1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "roots": [_serialize_tree_full(r) for r in roots],
    }
    # retour JSON pretty avec BOM-safe
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stock_export.json"'},
    )

# -------------------------------------------------
# IMPORT (JSON) — merge par défaut, replace si demandé
# -------------------------------------------------
@bp.post("/stock/import")
@login_required
def import_stock():
    if not require_admin():
        return _bad_request("Forbidden", 403)

    mode = (request.args.get("mode") or request.form.get("mode") or "merge").lower().strip()
    # Récup JSON soit via file upload, soit via body JSON
    data_obj: Optional[Dict[str, Any]] = None
    if "file" in request.files:
        try:
            data_obj = json.load(request.files["file"].stream)
        except Exception:
            return _bad_request("Invalid JSON file")
    else:
        data_obj = request.get_json(silent=True)
        if not isinstance(data_obj, dict) and not isinstance(data_obj, list):
            return _bad_request("JSON body expected")

    roots = data_obj.get("roots") if isinstance(data_obj, dict) else data_obj
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
