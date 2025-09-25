# app/stock/views.py — API CRUD hiérarchie de stock (ADMIN only)
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from ..models import Role, NodeType, StockNode
from .. import db
from .service import create_node, update_node, delete_node, duplicate_subtree, serialize_tree, list_roots

bp = Blueprint("stock", __name__)

def require_admin():
    return current_user.is_authenticated and current_user.role == Role.ADMIN

@bp.get("/stock/roots")
@login_required
def get_roots():
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    roots = list_roots()
    return jsonify([{"id": n.id, "name": n.name, "type": n.type.name, "level": n.level} for n in roots])

@bp.get("/stock/<int:node_id>/tree")
@login_required
def get_tree(node_id: int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    node = db.session.get(StockNode, node_id)
    if not node:
        return jsonify(error="Not found"), 404
    return jsonify(serialize_tree(node))

@bp.post("/stock")
@login_required
def post_node():
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    type_str = (data.get("type") or "GROUP").upper()
    parent_id = data.get("parent_id")
    quantity = data.get("quantity")
    if not name:
        return jsonify(error="name required"), 400
    try:
        type_ = NodeType[type_str]
    except KeyError:
        return jsonify(error="invalid type"), 400
    try:
        node = create_node(name=name, type_=type_, parent_id=parent_id, quantity=quantity)
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=node.id, name=node.name, type=node.type.name, level=node.level, quantity=node.quantity), 201

@bp.patch("/stock/<int:node_id>")
@login_required
def patch_node(node_id: int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    name = data.get("name")
    type_str = data.get("type")
    parent_id = data.get("parent_id") if "parent_id" in data else None
    quantity = data.get("quantity") if "quantity" in data else None
    type_ = None
    if type_str is not None:
        try:
            type_ = NodeType[type_str.upper()]
        except KeyError:
            return jsonify(error="invalid type"), 400
    try:
        node = update_node(node_id, name=name, type_=type_, parent_id=parent_id, quantity=quantity)
    except LookupError:
        return jsonify(error="Not found"), 404
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=node.id, name=node.name, type=node.type.name, level=node.level, quantity=node.quantity)

@bp.delete("/stock/<int:node_id>")
@login_required
def delete_node_api(node_id: int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    try:
        delete_node(node_id)
    except LookupError:
        return jsonify(error="Not found"), 404
    return jsonify(ok=True)

@bp.post("/stock/<int:node_id>/duplicate")
@login_required
def duplicate_node(node_id: int):
    if not require_admin():
        return jsonify(error="Forbidden"), 403
    data = request.get_json() or {}
    new_name = (data.get("new_name") or "").strip()
    new_parent_id = data.get("new_parent_id")
    if not new_name:
        return jsonify(error="new_name required"), 400
    try:
        new_root = duplicate_subtree(node_id, new_name=new_name, new_parent_id=new_parent_id)
    except LookupError:
        return jsonify(error="Not found"), 404
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=new_root.id, name=new_root.name, level=new_root.level, type=new_root.type.name), 201
