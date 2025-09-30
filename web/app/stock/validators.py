# app/stock/validators.py — garde-fous métier pour la hiérarchie de stock
from __future__ import annotations

from typing import Optional, Any

from ..models import NodeType

# Profondeur maximale autorisée dans l'arbre (1 = racine)
MAX_LEVEL: int = 5


def ensure_level_valid(level: int) -> None:
    """
    Vérifie que le niveau demandé est dans les bornes [1 .. MAX_LEVEL].
    """
    if not isinstance(level, int):
        raise ValueError("level must be an integer")
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"invalid level {level} (must be between 1 and {MAX_LEVEL})")


def ensure_item_quantity(type_: NodeType, quantity: Optional[int]) -> None:
    """
    - Pour ITEM : quantité requise, >= 0.
    - Pour GROUP : la quantité doit être None.
    """
    if type_ == NodeType.ITEM:
        if quantity is None:
            raise ValueError("quantity is required for ITEM")
        if not isinstance(quantity, int):
            raise ValueError("quantity must be an integer for ITEM")
        if quantity < 0:
            raise ValueError("quantity must be >= 0 for ITEM")
    else:
        # GROUP
        if quantity is not None:
            # On impose None pour éviter toute confusion dans la DB/UI.
            raise ValueError("GROUP cannot have a quantity (must be null)")


def compute_new_level(parent: Optional[Any]) -> int:
    """
    Calcule le niveau du nouveau nœud en fonction du parent.
    parent=None  -> niveau 1 (racine)
    sinon        -> parent.level + 1
    """
    return 1 if parent is None else int(getattr(parent, "level", 0)) + 1


def ensure_can_add_child(parent: Optional[Any]) -> None:
    """
    Autorise l'ajout d'un enfant sous 'parent' si :
      - parent est None (création d'une racine), OU
      - parent.type == GROUP
      - parent.level < MAX_LEVEL (on ne dépasse pas la profondeur max)
    """
    if parent is None:
        return
    # parent doit être un GROUP
    p_type = getattr(parent, "type", None)
    if p_type != NodeType.GROUP:
        raise ValueError("cannot add a child under a non-GROUP node")
    # profondeur max
    p_level = int(getattr(parent, "level", 0))
    if p_level >= MAX_LEVEL:
        raise ValueError(f"cannot add a child under level {p_level}: max depth {MAX_LEVEL} would be exceeded")


__all__ = [
    "MAX_LEVEL",
    "ensure_level_valid",
    "ensure_item_quantity",
    "compute_new_level",
    "ensure_can_add_child",
]
