# app/stock/views.py — API CRUD hiérarchie de stock (service-based)
from __future__ import annotations
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from ..models import Role, NodeType, StockNode
from .. import db
from .service import (
    create_node,
    update_node,
    delete_node,
    duplicate_subtree,
    serialize_tree,
    list_roots,
)

bp = Blueprint("stock", __name__)

# --------- Helpers rôles ---------
def is_admin() -> bool:
    return current_user.is_authenticated and current_user.role == Role.ADMIN

def can_view() -> bool:
    # lecture autorisée aux 3 rôles (ADMIN, CHEF, LECTURE)
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

def get_payload() -> dict:
    # tolère JSON et form-urlencoded
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

# --------- Lecture ---------
@bp.get("/stock/roots")
@login_required
def get_roots():
    if not can_view():
        return jsonify(error="Forbidden"), 403
    roots = list_roots()
    return jsonify([{"id": n.id, "name": n.name, "type": n.type.name, "level": n.level} for n in roots])

@bp.get("/stock/<int:node_id>/tree")
@login_required
def get_tree(node_id: int):
    if not can_view():
        return jsonify(error="Forbidden"), 403
    node = db.session.get(StockNode, node_id)
    if not node:
        return jsonify(error="Not found"), 404
    return jsonify(serialize_tree(node))

# --------- Création ---------
@bp.post("/stock")
@login_required
def post_node():
    if not is_admin():
        return jsonify(error="Forbidden"), 403
    data = get_payload()
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

# --------- Mise à jour ---------
@bp.patch("/stock/<int:node_id>")
@login_required
def patch_node(node_id: int):
    if not is_admin():
        return jsonify(error="Forbidden"), 403
    data = get_payload()
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

# --------- Suppression ---------
@bp.delete("/stock/<int:node_id>")
@login_required
def delete_node_api(node_id: int):
    if not is_admin():
        return jsonify(error="Forbidden"), 403

    # prise en charge optionnelle de la cascade (force)
    force_param = (request.args.get("force") or "").strip().lower()
    force = force_param in ("1", "true", "yes")

    try:
        # si ton service supporte delete_node(node_id, force=...), on le passe ;
        # sinon on retombe sur delete_node(node_id)
        try:
            delete_node(node_id, force=force)  # type: ignore
        except TypeError:
            if force:
                return jsonify(error="force not supported by service.delete_node"), 400
            delete_node(node_id)
    except LookupError:
        return jsonify(error="Not found"), 404
    except Exception as e:
        return jsonify(error=str(e)), 400

    return jsonify(ok=True)

# --------- Duplication ---------
@bp.post("/stock/<int:node_id>/duplicate")
@login_required
def duplicate_node(node_id: int):
    if not is_admin():
        return jsonify(error="Forbidden"), 403
    data = get_payload()
    new_name = (data.get("new_name") or "").strip() or None
    new_parent_id = data.get("new_parent_id")

    try:
        new_root = duplicate_subtree(node_id, new_name=new_name, new_parent_id=new_parent_id)
    except LookupError:
        return jsonify(error="Not found"), 404
    except Exception as e:
        return jsonify(error=str(e)), 400

    return jsonify(id=new_root.id, name=new_root.name, level=new_root.level, type=new_root.type.name), 201
