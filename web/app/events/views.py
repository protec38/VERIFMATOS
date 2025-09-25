# app/events/views.py — extrait : route /events/<id>/tree avec fallback
from __future__ import annotations
import uuid
from datetime import date
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from .. import db, socketio
from ..tree_query import build_event_tree
from ..models import (
    Event, EventStatus, Role,
    StockNode, NodeType, event_stock,
    EventShareLink, EventNodeStatus,
    VerificationRecord, ItemStatus,
)

bp = Blueprint("events", __name__)

# ... (garde les autres routes telles que je t’ai envoyées précédemment, y compris create_event)

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict() if request.form else {}
    return data

def _require_view(ev: Event):
    if not current_user.is_authenticated or current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)

@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    """Renvoie l'arbre de l'événement. Fallback : reconstruit depuis les parents associés."""
    ev = db.session.get(Event, event_id) or abort(404)
    _require_view(ev)

    try:
        tree = build_event_tree(event_id)
        if tree:
            return jsonify(tree)
    except Exception:
        # on continue sur le fallback
        pass

    # ----- Fallback local : on sérialise chaque parent associé puis ses enfants -----
    def serialize_node(n: StockNode) -> Dict[str, Any]:
        return {
            "id": n.id,
            "name": n.name,
            "type": n.type.name,
            "level": n.level,
            "quantity": n.quantity,
            "children": [serialize_node(c) for c in sorted(n.children, key=lambda x: (x.type.name, x.name.lower()))],
        }

    root_ids = [row[0] for row in db.session.execute(
        db.select(event_stock.c.node_id).where(event_stock.c.event_id == event_id)
    ).all()]

    if not root_ids:
        return jsonify([])

    roots = db.session.query(StockNode).filter(StockNode.id.in_(root_ids)).all()
    data = [serialize_node(r) for r in sorted(roots, key=lambda x: x.name.lower())]
    return jsonify(data)
