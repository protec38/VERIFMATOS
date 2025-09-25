# app/tree_query.py — Construction d'arbre hiérarchique pour un événement
from __future__ import annotations
from typing import Dict, Any, List
from . import db
from .models import StockNode, NodeType, event_stock

def _serialize(node: StockNode) -> Dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type.name,
        "level": node.level,
        "quantity": node.quantity,
        "children": [_serialize(c) for c in sorted(node.children, key=lambda x: (x.level, x.id))]
    }

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    # Récupère les racines attachées à l'événement puis sérialise récursivement
    rows = db.session.execute(event_stock.select().where(event_stock.c.event_id == event_id)).fetchall()
    root_ids = [r.node_id for r in rows]
    if not root_ids:
        return []
    roots = StockNode.query.filter(StockNode.id.in_(root_ids)).order_by(StockNode.id).all()
    return [_serialize(r) for r in roots]
