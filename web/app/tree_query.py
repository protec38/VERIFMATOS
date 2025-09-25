# app/tree_query.py — construit l'arbre 'tree' pour un événement ou un noeud
from __future__ import annotations
from typing import Dict, List, Any
from . import db
from .models import StockNode, NodeType, event_stock

def _node_to_dict(n: StockNode) -> Dict[str, Any]:
    t = n.type.name if hasattr(n.type, "name") else str(n.type)
    return {
        "id": n.id,
        "name": n.name,
        "level": n.level,
        "type": t,
        "quantity": n.quantity or 0,
        "children": [],
    }

def _children_for(node_id: int) -> List[StockNode]:
    return (
        StockNode.query
        .filter(StockNode.parent_id == node_id)
        .order_by(StockNode.type.desc(), StockNode.name.asc())
        .all()
    )

def _build_subtree(root: StockNode) -> Dict[str, Any]:
    d = _node_to_dict(root)
    stack = [(root.id, d)]
    while stack:
        nid, dict_ref = stack.pop()
        childs = _children_for(nid)
        for c in childs:
            cd = _node_to_dict(c)
            dict_ref["children"].append(cd)
            stack.append((c.id, cd))
    return d

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    roots = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
        .all()
    )
    tree: List[Dict[str, Any]] = []
    for r in roots:
        tree.append(_build_subtree(r))
    return tree
