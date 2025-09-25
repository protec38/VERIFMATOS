# app/stock/service.py — Services pour la gestion de la hiérarchie
from __future__ import annotations
from typing import Optional, Dict, Any, List
from .. import db
from ..models import StockNode, NodeType
from .validators import ensure_level_valid, ensure_item_quantity, compute_new_level, ensure_can_add_child

def create_node(*, name: str, type_: NodeType, parent_id: Optional[int], quantity: Optional[int]) -> StockNode:
    parent = db.session.get(StockNode, parent_id) if parent_id else None
    ensure_can_add_child(parent)
    level = compute_new_level(parent)
    ensure_level_valid(level)
    ensure_item_quantity(type_, quantity)

    node = StockNode(name=name, type=type_, level=level, parent=parent, quantity=quantity if type_ == NodeType.ITEM else None)
    db.session.add(node)
    db.session.commit()
    return node

def update_node(node_id: int, *, name: Optional[str] = None, type_: Optional[NodeType] = None,
                parent_id: Optional[int] = None, quantity: Optional[int] = None) -> StockNode:
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")

    # Move / reparent if needed
    if parent_id is not None and parent_id != (node.parent_id or None):
        new_parent = db.session.get(StockNode, parent_id) if parent_id else None
        ensure_can_add_child(new_parent)
        new_level = compute_new_level(new_parent)
        ensure_level_valid(new_level)
        # Also ensure subtree fits within MAX_LEVEL
        delta = new_level - node.level
        def check_subtree(n: StockNode):
            lvl = n.level + delta
            if lvl < 0 or lvl > 5:
                raise ValueError("moving would exceed max level 5")
            for c in n.children:
                check_subtree(c)
        check_subtree(node)
        node.parent = new_parent
        # Update levels for subtree
        def apply_level(n: StockNode):
            n.level = n.level + delta
            for c in n.children:
                apply_level(c)
        apply_level(node)

    if name is not None:
        node.name = name

    if type_ is not None and type_ != node.type:
        if node.children:
            raise ValueError("cannot change type on non-leaf/group with children")
        node.type = type_
    # quantity rule
    ensure_item_quantity(node.type, quantity if quantity is not None else node.quantity)
    if node.type == NodeType.ITEM and quantity is not None:
        node.quantity = quantity
    if node.type == NodeType.GROUP:
        node.quantity = None

    db.session.commit()
    return node

def delete_node(node_id: int) -> None:
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")
    # delete subtree
    def delete_rec(n: StockNode):
        for c in list(n.children):
            delete_rec(c)
        db.session.delete(n)
    delete_rec(node)
    db.session.commit()

def duplicate_subtree(root_id: int, *, new_name: Optional[str] = None, new_parent_id: Optional[int] = None) -> StockNode:
    root = db.session.get(StockNode, root_id)
    if not root:
        raise LookupError("node not found")
    parent = db.session.get(StockNode, new_parent_id) if new_parent_id else None
    ensure_can_add_child(parent)
    base_level = compute_new_level(parent)
    ensure_level_valid(base_level)

    # compute max depth
    max_depth = 0
    def depth(n: StockNode, d=0):
        nonlocal max_depth
        max_depth = max(max_depth, d)
        for c in n.children:
            depth(c, d+1)
    depth(root)
    if base_level + max_depth > 5:
        raise ValueError("duplication would exceed max level 5")

    # map old->new
    mapping = {}
    def clone(n: StockNode, parent_new: Optional[StockNode], level: int) -> StockNode:
        copy = StockNode(
            name=(new_name if n == root and new_name else n.name),
            type=n.type,
            level=level,
            parent=parent_new,
            quantity=n.quantity if n.type == NodeType.ITEM else None
        )
        db.session.add(copy)
        db.session.flush()  # allocate id for mapping
        mapping[n.id] = copy
        for c in n.children:
            clone(c, copy, level+1)
        return copy

    new_root = clone(root, parent, base_level)
    db.session.commit()
    return new_root

def serialize_tree(node: StockNode) -> Dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type.name,
        "level": node.level,
        "quantity": node.quantity,
        "children": [serialize_tree(c) for c in sorted(node.children, key=lambda x: (x.level, x.id))]
    }

def list_roots() -> List[StockNode]:
    return StockNode.query.filter_by(parent_id=None).order_by(StockNode.id).all()
