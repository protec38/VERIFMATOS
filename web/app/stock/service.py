# app/stock/service.py — Services pour la gestion de la hiérarchie
from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from .. import db
from ..models import StockNode, NodeType
from .validators import ensure_level_valid, ensure_item_quantity, compute_new_level, ensure_can_add_child, MAX_LEVEL

# -------------------------------------------------
# Utils internes
# -------------------------------------------------

def _is_descendant(potential_parent: StockNode, child: StockNode) -> bool:
    """Retourne True si potential_parent est dans la branche descendante de child (pour éviter cycles)."""
    stack = list(child.children)
    while stack:
        n = stack.pop()
        if n.id == potential_parent.id:
            return True
        stack.extend(n.children)
    return False

def _subtree_depth(n: StockNode) -> int:
    """Profondeur max du sous-arbre, 1 pour la racine n."""
    if not n.children:
        return 1
    return 1 + max(_subtree_depth(c) for c in n.children)

def _apply_level_rec(n: StockNode, level: int):
    ensure_level_valid(level)
    n.level = level
    for c in n.children:
        _apply_level_rec(c, level + 1)

# -------------------------------------------------
# CRUD de base
# -------------------------------------------------

def create_node(*, name: str, type_: NodeType, parent_id: Optional[int], quantity: Optional[int]) -> StockNode:
    parent = db.session.get(StockNode, parent_id) if parent_id else None
    ensure_can_add_child(parent)
    level = compute_new_level(parent)
    ensure_level_valid(level)
    ensure_item_quantity(type_, quantity)

    node = StockNode(
        name=name,
        type=type_,
        level=level,
        parent=parent,
        quantity=quantity if type_ == NodeType.ITEM else None,
    )
    db.session.add(node)
    db.session.commit()
    return node

def update_node(*, node_id: int, name: Optional[str] = None, parent_id: Optional[int] = None, quantity: Optional[int] = None) -> StockNode:
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")

    # Nom
    if name is not None:
        node.name = name.strip() or node.name

    # Quantité (seulement ITEM)
    if node.type == NodeType.ITEM:
        if quantity is not None:
            if quantity < 0:
                raise ValueError("quantity must be >= 0")
            node.quantity = quantity
    else:
        # Pour GROUP, quantité doit rester None
        node.quantity = None

    # Reparentage
    if parent_id is not None or parent_id is None:
        # Distinction: si parent_id est fourni explicitement (même None), on traite
        parent = db.session.get(StockNode, parent_id) if parent_id else None
        if parent is not None:
            ensure_can_add_child(parent)
            if _is_descendant(parent, node):
                raise ValueError("cannot set parent to a descendant (cycle)")
        # Calcul du nouveau niveau + validation profondeur
        new_level = compute_new_level(parent)
        depth = _subtree_depth(node)
        if new_level + depth - 1 > MAX_LEVEL:
            raise ValueError(f"moving would exceed max level {MAX_LEVEL}")
        node.parent = parent
        _apply_level_rec(node, new_level)

    db.session.commit()
    return node

def delete_node(node_id: int):
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")
    # suppression du sous-arbre (post-order)
    def rec(n: StockNode):
        for c in list(n.children):
            rec(c)
        db.session.delete(n)
    rec(node)
    db.session.commit()

def duplicate_subtree(root_id: int, *, new_name: Optional[str] = None, new_parent_id: Optional[int] = None) -> StockNode:
    root = db.session.get(StockNode, root_id)
    if not root:
        raise LookupError("root not found")
    parent = db.session.get(StockNode, new_parent_id) if new_parent_id else None
    ensure_can_add_child(parent)

    base_level = compute_new_level(parent)
    ensure_level_valid(base_level)

    # Vérifier profondeur totale
    def depth(n: StockNode) -> int:
        if not n.children:
            return 1
        return 1 + max(depth(c) for c in n.children)
    max_depth = depth(root)
    if base_level + max_depth - 1 > MAX_LEVEL:
        raise ValueError(f"duplication would exceed max level {MAX_LEVEL}")

    mapping: Dict[int, StockNode] = {}

    def clone(n: StockNode, parent_new: Optional[StockNode], level: int) -> StockNode:
        copy = StockNode(
            name=(new_name if n == root and new_name else n.name),
            type=n.type,
            level=level,
            parent=parent_new,
            quantity=n.quantity if n.type == NodeType.ITEM else None,
        )
        # Copier aussi la péremption pour ITEM
        if n.type == NodeType.ITEM:
            copy.expiry_date = getattr(n, "expiry_date", None)
        db.session.add(copy)
        db.session.flush()  # obtenir l'id
        mapping[n.id] = copy
        for c in n.children:
            clone(c, copy, level + 1)
        return copy

    new_root = clone(root, parent, base_level)
    db.session.commit()
    return new_root

def serialize_tree(node: StockNode) -> Dict[str, Any]:
    """Sérialise un sous-arbre pour l'UI d'admin (manage.html)."""
    out: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": node.type.name,
        "level": node.level,
        "quantity": node.quantity if node.type == NodeType.ITEM else None,
        # Inclure la date de péremption pour ITEM (string ISO ou None)
        "expiry_date": node.expiry_date.isoformat() if getattr(node, "expiry_date", None) else None,
        "children": [],
    }
    for c in sorted(node.children, key=lambda x: (x.level, x.id)):
        out["children"].append(serialize_tree(c))
    return out

def list_roots() -> List[StockNode]:
    return StockNode.query.filter_by(parent_id=None).order_by(StockNode.id).all()
