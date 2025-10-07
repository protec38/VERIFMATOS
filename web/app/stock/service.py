# app/stock/service.py — Services hiérarchie de stock
from __future__ import annotations
from typing import Optional, Dict, Any, List

from .. import db
from ..models import (
    StockNode,
    NodeType,
    PeriodicVerificationRecord,
    VerificationRecord,
    EventNodeStatus,
    EventTemplateNode,
    event_stock,
)
from .validators import (
    ensure_level_valid,
    ensure_item_quantity,
    compute_new_level,
    ensure_can_add_child,
    MAX_LEVEL,
)

# -------------------------------------------------
# Utils internes
# -------------------------------------------------
def _is_descendant(potential_parent: StockNode, child: StockNode) -> bool:
    """
    True si 'potential_parent' se trouve dans le sous-arbre de 'child' (évite les cycles).
    """
    stack = list(child.children)
    while stack:
        n = stack.pop()
        if n.id == potential_parent.id:
            return True
        stack.extend(n.children)
    return False

def _subtree_depth(n: StockNode) -> int:
    """
    Profondeur max du sous-arbre (1 = n lui-même).
    """
    if not n.children:
        return 1
    return 1 + max(_subtree_depth(c) for c in n.children)

def _apply_level_rec(n: StockNode, level: int):
    ensure_level_valid(level)
    n.level = level
    for c in n.children:
        _apply_level_rec(c, level + 1)

# -------------------------------------------------
# CRUD
# -------------------------------------------------
def create_node(
    *,
    name: str,
    type_: NodeType,
    parent_id: Optional[int],
    quantity: Optional[int],
    unique_item: bool = False,
    unique_quantity: Optional[int] = None,
) -> StockNode:
    """
    Crée un noeud:
      - parent_id None => racine (level=1)
      - type GROUP => quantity ignorée (None)
      - type ITEM  => quantity >= 0 requise
    """
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
    if type_ == NodeType.GROUP:
        node.unique_item = bool(unique_item)
        if node.unique_item:
            if unique_quantity is None:
                raise ValueError("unique_quantity required when unique_item is true")
            if not isinstance(unique_quantity, int) or unique_quantity < 0:
                raise ValueError("unique_quantity must be an integer >= 0")
            node.unique_quantity = unique_quantity
        else:
            node.unique_quantity = None
    else:
        node.unique_item = False
        node.unique_quantity = None
    db.session.add(node)
    db.session.commit()
    return node

def update_node(
    *,
    node_id: int,
    name: Optional[str] = None,
    parent_id: Optional[int] = None,
    quantity: Optional[int] = None,
    unique_item: Optional[bool] = None,
    unique_quantity: Optional[int] = None,
) -> StockNode:
    """
    Met à jour un noeud:
      - name (optionnel)
      - quantity (ITEM uniquement)
      - reparentage si parent_id différent de l'actuel (y compris vers None pour racine)
    """
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")

    # Nom
    if name is not None:
        node.name = name.strip() or node.name

    # Quantité
    if node.type == NodeType.ITEM:
        if quantity is not None:
            if quantity < 0:
                raise ValueError("quantity must be >= 0")
            node.quantity = quantity
    else:
        node.quantity = None  # GROUP: force None
        if unique_item is not None:
            node.unique_item = bool(unique_item)
            if not node.unique_item:
                node.unique_quantity = None
        if node.unique_item:
            if unique_quantity is not None:
                if not isinstance(unique_quantity, int) or unique_quantity < 0:
                    raise ValueError("unique_quantity must be >= 0")
                node.unique_quantity = unique_quantity
            elif node.unique_quantity is None:
                raise ValueError("unique_quantity required when unique_item is true")
        else:
            node.unique_quantity = None

    # Reparentage uniquement si changement effectif
    if parent_id != node.parent_id:
        parent = db.session.get(StockNode, parent_id) if parent_id else None
        if parent is not None:
            ensure_can_add_child(parent)
            # pas de cycle: le nouveau parent ne peut pas être un descendant du noeud
            if _is_descendant(parent, node):
                raise ValueError("cannot set parent to a descendant (cycle)")
        # Profondeur max respectée pour tout le sous-arbre déplacé
        new_level = compute_new_level(parent)
        depth = _subtree_depth(node)
        if new_level + depth - 1 > MAX_LEVEL:
            raise ValueError(f"moving would exceed max level {MAX_LEVEL}")

        node.parent = parent
        _apply_level_rec(node, new_level)

    db.session.commit()
    return node

def delete_node(node_id: int):
    """
    Supprime le noeud et tout son sous-arbre (post-order).
    """
    node = db.session.get(StockNode, node_id)
    if not node:
        raise LookupError("node not found")

    node_ids: list[int] = []

    def collect(n: StockNode):
        node_ids.append(n.id)
        for c in n.children:
            collect(c)

    collect(node)

    if node_ids:
        db.session.query(PeriodicVerificationRecord).filter(
            PeriodicVerificationRecord.node_id.in_(node_ids)
        ).delete(synchronize_session=False)
        VerificationRecord.query.filter(
            VerificationRecord.node_id.in_(node_ids)
        ).delete(synchronize_session=False)
        EventNodeStatus.query.filter(
            EventNodeStatus.node_id.in_(node_ids)
        ).delete(synchronize_session=False)
        db.session.execute(
            event_stock.delete().where(event_stock.c.node_id.in_(node_ids))
        )
        db.session.query(EventTemplateNode).filter(
            EventTemplateNode.node_id.in_(node_ids)
        ).delete(synchronize_session=False)

    def rec(n: StockNode):
        for c in list(n.children):
            rec(c)
        db.session.delete(n)

    rec(node)
    db.session.commit()

def duplicate_subtree(root_id: int, *, new_name: Optional[str] = None, new_parent_id: Optional[int] = None) -> StockNode:
    """
    Duplique le sous-arbre 'root_id' sous 'new_parent_id' (ou racine), avec:
      - contrôle de profondeur totale
      - copie de quantity (ITEM) et expiry_date (ITEM)
      - rename de la racine si new_name fourni
    """
    root = db.session.get(StockNode, root_id)
    if not root:
        raise LookupError("root not found")

    parent = db.session.get(StockNode, new_parent_id) if new_parent_id else None
    ensure_can_add_child(parent)

    base_level = compute_new_level(parent)
    ensure_level_valid(base_level)

    # profondeur totale
    def depth(n: StockNode) -> int:
        if not n.children:
            return 1
        return 1 + max(depth(c) for c in n.children)

    max_depth = depth(root)
    if base_level + max_depth - 1 > MAX_LEVEL:
        raise ValueError(f"duplication would exceed max level {MAX_LEVEL}")

    def clone(n: StockNode, parent_new: Optional[StockNode], level: int) -> StockNode:
        copy = StockNode(
            name=(new_name if n == root and new_name else n.name),
            type=n.type,
            level=level,
            parent=parent_new,
            quantity=n.quantity if n.type == NodeType.ITEM else None,
        )
        if n.type == NodeType.GROUP:
            copy.unique_item = bool(getattr(n, "unique_item", False))
            copy.unique_quantity = getattr(n, "unique_quantity", None) if copy.unique_item else None
        else:
            copy.unique_item = False
            copy.unique_quantity = None
        # Copier la péremption pour ITEM
        if n.type == NodeType.ITEM:
            copy.expiry_date = getattr(n, "expiry_date", None)
        db.session.add(copy)
        db.session.flush()
        for c in n.children:
            clone(c, copy, level + 1)
        return copy

    new_root = clone(root, parent, base_level)
    db.session.commit()
    return new_root

def serialize_tree(node: StockNode) -> Dict[str, Any]:
    """
    Sérialise un sous-arbre pour l’UI admin (manage.html).
    """
    out: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": node.type.name,
        "level": node.level,
        "quantity": node.quantity if node.type == NodeType.ITEM else None,
        "unique_item": bool(getattr(node, "unique_item", False)),
        "unique_quantity": getattr(node, "unique_quantity", None) if getattr(node, "unique_item", False) else None,
        # date de péremption pour ITEM (string ISO ou None)
        "expiry_date": node.expiry_date.isoformat() if getattr(node, "expiry_date", None) else None,
        "children": [],
    }
    for c in sorted(node.children, key=lambda x: (x.level, x.id)):
        out["children"].append(serialize_tree(c))
    return out

def list_roots() -> List[StockNode]:
    """
    Liste ordonnée de toutes les racines (parent_id=None).
    """
    return StockNode.query.filter_by(parent_id=None).order_by(StockNode.id).all()
