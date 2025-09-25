# app/tree_query.py
from __future__ import annotations
from typing import Dict, List
from . import db
from .models import StockNode, NodeType, event_stock

MAX_DEPTH = 5  # jusqu’à 5 sous-niveaux comme demandé

def _serialize_node(node: StockNode, depth: int = 0) -> Dict:
    """Sérialise un nœud et ses enfants récursivement, avec limite de profondeur."""
    data: Dict = {
        "id": node.id,
        "name": node.name,
        "type": node.type.name if hasattr(node.type, "name") else str(node.type),
        "level": node.level,
        "quantity": node.quantity if getattr(node, "quantity", None) is not None else None,
        "children": [],
    }
    if depth >= MAX_DEPTH:
        return data

    # On récupère les enfants, tri : GROUP avant ITEM, puis par nom
    children = (
        StockNode.query
        .filter(StockNode.parent_id == node.id)
        .order_by(StockNode.type.desc(), StockNode.name.asc())
        .all()
    )
    for ch in children:
        data["children"].append(_serialize_node(ch, depth + 1))
    return data

def build_event_tree(event_id: int) -> List[Dict]:
    """Construit l'arbre complet pour un événement :
    - Récupère les parents racine associés via event_stock
    - Sérialise chaque sous-arbre
    """
    roots = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
        .all()
    )
    out: List[Dict] = []
    for r in roots:
        out.append(_serialize_node(r, depth=0))
    return out
